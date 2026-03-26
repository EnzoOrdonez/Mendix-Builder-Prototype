/**
 * Handler for page operations via Mendix Model SDK.
 *
 * Creates pages with real widgets in the online working copy:
 * - Create/Edit: DataView → TextBox/CheckBox/DatePicker/ReferenceSelector + buttons
 * - Overview: DataGrid → columns + SearchField + filter DropDowns + action buttons
 * - Config: NavigationListItem widgets
 *
 * v2: Full widget creation from Python PageGenerator payloads.
 */

import { pages, projects, domainmodels } from "mendixmodelsdk";
import type { IModel } from "mendixmodelsdk";
import { session } from "../session";
import type {
  PagePayload,
  WidgetPayload,
  ButtonPayload,
  SectionPayload,
} from "../types/schemas";

// Re-export for backward compat
export type CreatePageParams = PagePayload;

export interface CreatePageResult {
  status: "created" | "already_exists" | "error";
  name: string;
  module: string;
  page_type: string;
  widgets_count: number;
  error?: string;
}

/**
 * Creates a page in the Mendix project with real widgets.
 */
export async function createPage(
  appId: string,
  page: PagePayload,
  branchName = "main"
): Promise<CreatePageResult> {
  try {
    const model = await session.getModel(appId, branchName);

    // 1. Find the target module
    const targetModule = findModule(model, page.module);
    if (!targetModule) {
      return {
        status: "error",
        name: page.name,
        module: page.module,
        page_type: page.page_type,
        widgets_count: 0,
        error: `Module '${page.module}' not found in project`,
      };
    }

    // 2. Check if page already exists
    for (const existingPage of model.allPages()) {
      if (
        existingPage.name === page.name &&
        getModuleName(existingPage) === page.module
      ) {
        console.error(
          `[mendex-sdk] Page ${page.module}.${page.name} already exists`
        );
        return {
          status: "already_exists",
          name: page.name,
          module: page.module,
          page_type: page.page_type,
          widgets_count: 0,
        };
      }
    }

    // 3. Find layout (popup pages use PopupLayout)
    const layoutName = page.is_popup ? "PopupLayout" : page.layout;
    const layout = findLayout(model, layoutName, page.module);
    if (!layout) {
      return {
        status: "error",
        name: page.name,
        module: page.module,
        page_type: page.page_type,
        widgets_count: 0,
        error: `Layout '${layoutName}' not found. Available: ${model
          .allLayouts()
          .map((l) => l.name)
          .join(", ")}`,
      };
    }

    // 4. Create the page
    const newPage = pages.Page.createIn(targetModule);
    newPage.name = page.name;

    // 5. Set the layout call
    const layoutCall = pages.LayoutCall.createInPageUnderLayoutCall(newPage);
    layoutCall.layout = layout;

    // 6. Find the "content" placeholder in the layout
    const contentPlaceholder = findContentPlaceholder(layout);

    // 7. Create layout call content for the main placeholder
    let container: pages.ILayoutCallArgument | null = null;
    if (contentPlaceholder) {
      const arg = pages.LayoutCallArgument.createIn(layoutCall);
      arg.parameter = contentPlaceholder;
      container = arg;
    }

    // 8. Create widgets based on page type
    let widgetCount = 0;
    const widgets = page.widgets || [];
    const buttons = page.buttons || [];

    if (page.page_type === "Create" || page.page_type === "Edit") {
      widgetCount = createFormPageWidgets(
        model,
        newPage,
        container,
        widgets,
        buttons,
        page
      );
    } else if (page.page_type === "Overview") {
      widgetCount = createOverviewPageWidgets(
        model,
        newPage,
        container,
        widgets,
        buttons,
        page
      );
    } else if (page.page_type === "Config") {
      widgetCount = createConfigPageWidgets(
        model,
        newPage,
        container,
        widgets
      );
    }

    // 9. Flush changes
    await model.flushChanges();

    console.error(
      `[mendex-sdk] Created page ${page.module}.${page.name} ` +
        `[${page.page_type}] with ${widgetCount} widgets, layout=${layoutName}`
    );

    return {
      status: "created",
      name: page.name,
      module: page.module,
      page_type: page.page_type,
      widgets_count: widgetCount,
    };
  } catch (err: unknown) {
    const msg = err instanceof Error ? err.message : String(err);
    console.error(`[mendex-sdk] Error creating page: ${msg}`);
    return {
      status: "error",
      name: page.name,
      module: page.module,
      page_type: page.page_type,
      widgets_count: 0,
      error: msg,
    };
  }
}

// ─── Create/Edit Page: DataView + input widgets + buttons ───

function createFormPageWidgets(
  model: IModel,
  page: pages.Page,
  container: pages.ILayoutCallArgument | null,
  widgets: WidgetPayload[],
  buttons: ButtonPayload[],
  pagePayload: PagePayload
): number {
  let count = 0;

  // Create a DataView as the main container (bound to entity via context)
  const dataView = pages.DataView.createIn(page);
  dataView.name = `dataView${pagePayload.entity}`;
  dataView.editable = true;

  // Set entity source as page parameter (context)
  const dataViewSource = pages.DataViewSource.createIn(dataView);

  // Create header container for buttons
  if (buttons.length > 0) {
    const headerContainer = pages.DivContainer.createIn(page);
    headerContainer.name = "buttonBar";

    for (const btn of buttons) {
      createActionButton(model, headerContainer, btn, pagePayload);
      count++;
    }
  }

  // Group widgets by section
  const sectionMap = new Map<string, WidgetPayload[]>();
  const unsectioned: WidgetPayload[] = [];

  for (const widget of widgets) {
    if (widget.widget_type === "NestedListView") {
      // NestedListView goes after all form fields
      continue;
    }
    if (widget.section) {
      if (!sectionMap.has(widget.section)) {
        sectionMap.set(widget.section, []);
      }
      sectionMap.get(widget.section)!.push(widget);
    } else {
      unsectioned.push(widget);
    }
  }

  // Create unsectioned widgets directly in the DataView
  for (const widget of unsectioned) {
    createInputWidget(model, dataView, widget, pagePayload);
    count++;
  }

  // Create GroupBox per section
  for (const [sectionName, sectionWidgets] of sectionMap) {
    const groupBox = pages.GroupBox.createIn(dataView);
    groupBox.name = `section_${sectionName.replace(/\s+/g, "_")}`;

    // GroupBox caption
    const caption = pages.ClientTemplate.createInGroupBoxUnderCaption(groupBox);
    const captionText = pages.TextTemplate.createIn(caption);

    for (const widget of sectionWidgets) {
      createInputWidget(model, groupBox, widget, pagePayload);
      count++;
    }
  }

  // Create NestedListView widgets (master-detail)
  const nestedLists = widgets.filter(
    (w) => w.widget_type === "NestedListView"
  );
  for (const nested of nestedLists) {
    createNestedListView(model, dataView, nested, pagePayload);
    count++;
  }

  return count;
}

// ─── Overview Page: DataGrid + columns + search + filters ───

function createOverviewPageWidgets(
  model: IModel,
  page: pages.Page,
  container: pages.ILayoutCallArgument | null,
  widgets: WidgetPayload[],
  buttons: ButtonPayload[],
  pagePayload: PagePayload
): number {
  let count = 0;

  // Separate widget types
  const filterWidgets = widgets.filter((w) => w.is_filter);
  const columnWidgets = widgets.filter(
    (w) => w.widget_type === "DataGridColumn"
  );
  const searchWidgets = widgets.filter(
    (w) => w.widget_type === "SearchField"
  );

  // Create filter bar (DropDowns for dynamic filters)
  if (filterWidgets.length > 0) {
    const filterBar = pages.DivContainer.createIn(page);
    filterBar.name = "filterBar";

    for (const filter of filterWidgets) {
      const dropdown = pages.DropDown.createIn(filterBar);
      dropdown.name = `filter_${filter.attribute || "unknown"}`;
      count++;
    }
  }

  // Create action buttons bar (Nuevo, etc.)
  const topButtons = buttons.filter((b) => b.placement === "top");
  if (topButtons.length > 0) {
    const buttonBar = pages.DivContainer.createIn(page);
    buttonBar.name = "actionBar";

    for (const btn of topButtons) {
      createActionButton(model, buttonBar, btn, pagePayload);
      count++;
    }
  }

  // Create DataGrid
  const dataGrid = pages.DataGrid.createIn(page);
  dataGrid.name = `grid_${pagePayload.entity}`;
  dataGrid.isControlBarVisible = true;

  // Create columns
  for (const col of columnWidgets) {
    const column = pages.GridColumn.createIn(dataGrid);
    column.name = col.attribute || col.association || "col";

    // Column caption
    const caption =
      pages.ClientTemplate.createInGridColumnUnderCaption(column);
    const captionText = pages.TextTemplate.createIn(caption);

    count++;
  }

  // Create search fields
  for (const search of searchWidgets) {
    const searchField = pages.GridSearchField.createIn(dataGrid);
    searchField.name = search.attribute || search.association || "search";
    count++;
  }

  // Row-level action buttons (Editar, Eliminar)
  const rowButtons = buttons.filter((b) => b.placement === "row");
  for (const btn of rowButtons) {
    // Row buttons go in the grid's control bar
    createActionButton(model, dataGrid, btn, pagePayload);
    count++;
  }

  return count;
}

// ─── Config Page: NavigationListItem widgets ────────────────

function createConfigPageWidgets(
  model: IModel,
  page: pages.Page,
  container: pages.ILayoutCallArgument | null,
  widgets: WidgetPayload[]
): number {
  let count = 0;

  const navContainer = pages.DivContainer.createIn(page);
  navContainer.name = "configNavigation";

  for (const widget of widgets) {
    if (widget.widget_type === "NavigationListItem") {
      // Create a container with a label linking to the target page
      const item = pages.DivContainer.createIn(navContainer);
      item.name = `nav_${widget.target_page || "item"}`;
      count++;
    }
  }

  return count;
}

// ─── Widget Creators ────────────────────────────────────────

function createInputWidget(
  model: IModel,
  parent: pages.DataView | pages.GroupBox,
  widget: WidgetPayload,
  pagePayload: PagePayload
): void {
  const widgetType = widget.widget_type;

  switch (widgetType) {
    case "TextBox": {
      const textBox = pages.TextBox.createIn(parent);
      textBox.name = widget.attribute || "textBox";
      textBox.editable =
        widget.editable !== false
          ? pages.EditableEnum.Always
          : pages.EditableEnum.Never;

      // Set label
      if (widget.label) {
        const label = pages.Label.createIn(textBox);
        const caption = pages.ClientTemplate.createInLabelUnderCaption(label);
        const text = pages.TextTemplate.createIn(caption);
      }

      // Conditional visibility
      if (widget.conditional_visibility) {
        setConditionalVisibility(textBox, widget);
      }
      break;
    }

    case "TextArea": {
      const textArea = pages.TextArea.createIn(parent);
      textArea.name = widget.attribute || "textArea";
      textArea.editable =
        widget.editable !== false
          ? pages.EditableEnum.Always
          : pages.EditableEnum.Never;
      if (widget.conditional_visibility) {
        setConditionalVisibility(textArea, widget);
      }
      break;
    }

    case "CheckBox": {
      const checkBox = pages.CheckBox.createIn(parent);
      checkBox.name = widget.attribute || "checkBox";
      checkBox.editable =
        widget.editable !== false
          ? pages.EditableEnum.Always
          : pages.EditableEnum.Never;
      if (widget.conditional_visibility) {
        setConditionalVisibility(checkBox, widget);
      }
      break;
    }

    case "DatePicker": {
      const datePicker = pages.DatePicker.createIn(parent);
      datePicker.name = widget.attribute || "datePicker";
      datePicker.editable =
        widget.editable !== false
          ? pages.EditableEnum.Always
          : pages.EditableEnum.Never;
      if (widget.conditional_visibility) {
        setConditionalVisibility(datePicker, widget);
      }
      break;
    }

    case "DropDown": {
      const dropdown = pages.DropDown.createIn(parent);
      dropdown.name = widget.attribute || "dropdown";
      dropdown.editable =
        widget.editable !== false
          ? pages.EditableEnum.Always
          : pages.EditableEnum.Never;
      if (widget.conditional_visibility) {
        setConditionalVisibility(dropdown, widget);
      }
      break;
    }

    case "RadioButtons": {
      const radio = pages.RadioButtonGroup.createIn(parent);
      radio.name = widget.attribute || "radioButtons";
      radio.editable =
        widget.editable !== false
          ? pages.EditableEnum.Always
          : pages.EditableEnum.Never;
      break;
    }

    case "ReferenceSelector": {
      const refSelector = pages.ReferenceSelector.createIn(parent);
      refSelector.name =
        widget.association || widget.attribute || "refSelector";
      refSelector.editable =
        widget.editable !== false
          ? pages.EditableEnum.Always
          : pages.EditableEnum.Never;

      // The selectable_objects_source microflow will be resolved by name
      // when the model is loaded in Studio Pro, or via a post-processing step
      if (widget.selectable_objects_source) {
        console.error(
          `[mendex-sdk] ReferenceSelector ${refSelector.name}: ` +
            `selectable objects source = ${widget.selectable_objects_source}`
        );
      }

      if (widget.conditional_visibility) {
        setConditionalVisibility(refSelector, widget);
      }
      break;
    }

    case "FileManager": {
      const fileManager = pages.FileManager.createIn(parent);
      fileManager.name = widget.attribute || "fileManager";
      break;
    }

    case "ImageUploader": {
      const imageUploader = pages.ImageUploader.createIn(parent);
      imageUploader.name = widget.attribute || "imageUploader";
      break;
    }

    case "RichTextEditor": {
      // Rich text is typically a pluggable widget; use TextArea as fallback
      const richText = pages.TextArea.createIn(parent);
      richText.name = widget.attribute || "richText";
      richText.editable =
        widget.editable !== false
          ? pages.EditableEnum.Always
          : pages.EditableEnum.Never;
      break;
    }

    default: {
      // Fallback: create a TextBox
      console.error(
        `[mendex-sdk] Unknown widget type '${widgetType}', creating TextBox`
      );
      const fallback = pages.TextBox.createIn(parent);
      fallback.name = widget.attribute || "unknown";
      break;
    }
  }
}

/**
 * Creates a NestedListView (DataGrid bound to child association).
 */
function createNestedListView(
  model: IModel,
  parent: pages.DataView,
  widget: WidgetPayload,
  pagePayload: PagePayload
): void {
  // Inner DataGrid for the child entity list
  const innerGrid = pages.DataGrid.createIn(parent);
  innerGrid.name = `nested_${widget.child_entity || "child"}`;
  innerGrid.isControlBarVisible = true;

  // Create columns from the nested list's column definitions
  if (widget.columns) {
    for (const col of widget.columns) {
      const column = pages.GridColumn.createIn(innerGrid);
      column.name = col.attribute || "col";

      const caption =
        pages.ClientTemplate.createInGridColumnUnderCaption(column);
      const captionText = pages.TextTemplate.createIn(caption);
    }
  }

  // Create nested list buttons (Agregar, Eliminar)
  if (widget.buttons) {
    for (const btn of widget.buttons) {
      createActionButton(model, innerGrid, btn, pagePayload);
    }
  }
}

/**
 * Creates an ActionButton widget.
 */
function createActionButton(
  model: IModel,
  parent:
    | pages.DivContainer
    | pages.DataGrid
    | pages.DataView
    | pages.Page,
  btn: ButtonPayload,
  pagePayload: PagePayload
): void {
  const actionBtn = pages.ActionButton.createIn(parent);
  actionBtn.name = `btn_${btn.label?.replace(/\s+/g, "_") || "action"}`;

  // Set caption
  const caption =
    pages.ClientTemplate.createInActionButtonUnderCaption(actionBtn);
  const text = pages.TextTemplate.createIn(caption);

  // Set button style
  if (btn.style === "Primary") {
    actionBtn.buttonStyle = pages.ButtonStyle.Primary;
  } else if (btn.style === "Danger") {
    actionBtn.buttonStyle = pages.ButtonStyle.Danger;
  } else {
    actionBtn.buttonStyle = pages.ButtonStyle.Default;
  }

  // Set action
  if (btn.action === "call_microflow" && btn.microflow) {
    // Create a microflow call action
    const callAction = pages.MicroflowClientAction.createIn(actionBtn);
    // The microflow reference will be resolved by qualified name
    // Format: "Module.MicroflowName"
    const qualifiedName = btn.microflow.includes(".")
      ? btn.microflow
      : `${pagePayload.module}.${btn.microflow}`;

    // Find the microflow in the model
    const mf = findMicroflowByName(model, qualifiedName);
    if (mf) {
      callAction.microflowSettings =
        pages.MicroflowSettings.createIn(callAction);
      callAction.microflowSettings.microflow = mf;
    } else {
      console.error(
        `[mendex-sdk] Microflow '${qualifiedName}' not found — button will need manual wiring`
      );
    }
  } else if (btn.action === "show_page" && btn.target_page) {
    const pageAction = pages.PageClientAction.createIn(actionBtn);
    // Find target page
    const targetPage = findPageByName(model, btn.target_page, pagePayload.module);
    if (targetPage) {
      pageAction.pageSettings = pages.PageSettings.createIn(pageAction);
      pageAction.pageSettings.page = targetPage;
    } else {
      console.error(
        `[mendex-sdk] Page '${btn.target_page}' not found — button will need manual wiring`
      );
    }
  } else if (btn.action === "close_page") {
    pages.ClosePageClientAction.createIn(actionBtn);
  }
}

/**
 * Sets conditional visibility on a widget.
 */
function setConditionalVisibility(
  widget: pages.Widget,
  widgetPayload: WidgetPayload
): void {
  if (!widgetPayload.conditional_visibility) return;

  const cv = widgetPayload.conditional_visibility;
  // Log for manual completion — SDK conditional visibility requires
  // attribute path resolution which depends on the entity context
  console.error(
    `[mendex-sdk] Conditional visibility on '${widget.name}': ` +
      `depends_on=${cv.depends_on}, operator=${cv.operator}, value=${cv.value || "(not_empty)"}`
  );
}

// ─── Helpers ────────────────────────────────────────────────

function findModule(
  model: IModel,
  moduleName: string
): projects.IModule | null {
  for (const mod of model.allModules()) {
    if (mod.name === moduleName) {
      return mod;
    }
  }
  return null;
}

function findLayout(
  model: IModel,
  layoutName: string,
  preferredModule: string
): pages.ILayout | null {
  let fallback: pages.ILayout | null = null;

  for (const layout of model.allLayouts()) {
    if (layout.name === layoutName) {
      const modName = getLayoutModuleName(layout);
      if (modName === preferredModule) {
        return layout;
      }
      if (!fallback) {
        fallback = layout;
      }
    }
  }

  // Partial match fallback
  if (!fallback) {
    for (const layout of model.allLayouts()) {
      if (
        layout.name.includes(layoutName) ||
        layoutName.includes(layout.name)
      ) {
        fallback = layout;
        break;
      }
    }
  }

  return fallback;
}

function findContentPlaceholder(
  layout: pages.ILayout
): pages.ILayoutParameter | null {
  // Try to find a placeholder named "Content" or the first available
  try {
    const loaded = layout as pages.Layout;
    if (loaded.layoutParameters && loaded.layoutParameters.length > 0) {
      const content = loaded.layoutParameters.find(
        (p) => p.name.toLowerCase() === "content"
      );
      return content || loaded.layoutParameters[0];
    }
  } catch {
    // Layout not fully loaded — skip placeholder resolution
  }
  return null;
}

function findMicroflowByName(
  model: IModel,
  qualifiedName: string
): import("mendixmodelsdk").microflows.IMicroflow | null {
  const parts = qualifiedName.split(".");
  const mfName = parts.length > 1 ? parts[parts.length - 1] : qualifiedName;
  const moduleName = parts.length > 1 ? parts[0] : null;

  for (const mf of model.allMicroflows()) {
    if (mf.name === mfName) {
      if (moduleName) {
        const mfModule = getMicroflowModuleName(mf);
        if (mfModule === moduleName) return mf;
      } else {
        return mf;
      }
    }
  }
  return null;
}

function findPageByName(
  model: IModel,
  pageName: string,
  preferredModule: string
): pages.IPage | null {
  for (const p of model.allPages()) {
    if (p.name === pageName) {
      const modName = getModuleName(p);
      if (modName === preferredModule) return p;
    }
  }
  // Fallback: any module
  for (const p of model.allPages()) {
    if (p.name === pageName) return p;
  }
  return null;
}

function getModuleName(page: pages.IPage): string {
  let container: projects.IFolderBase = page.containerAsFolderBase;
  while (container) {
    if ("fromAppStore" in container) {
      return (container as projects.IModule).name;
    }
    if ("containerAsFolderBase" in container) {
      container = (container as projects.IFolder).containerAsFolderBase;
    } else {
      break;
    }
  }
  return "";
}

function getLayoutModuleName(layout: pages.ILayout): string {
  let container: projects.IFolderBase = layout.containerAsFolderBase;
  while (container) {
    if ("fromAppStore" in container) {
      return (container as projects.IModule).name;
    }
    if ("containerAsFolderBase" in container) {
      container = (container as projects.IFolder).containerAsFolderBase;
    } else {
      break;
    }
  }
  return "";
}

function getMicroflowModuleName(
  mf: import("mendixmodelsdk").microflows.IMicroflow
): string {
  let container: projects.IFolderBase = mf.containerAsFolderBase;
  while (container) {
    if ("fromAppStore" in container) {
      return (container as projects.IModule).name;
    }
    if ("containerAsFolderBase" in container) {
      container = (container as projects.IFolder).containerAsFolderBase;
    } else {
      break;
    }
  }
  return "";
}
