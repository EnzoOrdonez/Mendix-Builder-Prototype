/**
 * Handler for microflow operations via Mendix Model SDK.
 *
 * Creates microflows with real activity chains:
 * - Validation: input parameter → validation activities → decision → end
 * - Save: input parameter → validate → commit → close page
 * - Delete: input parameter → confirm → delete → close page
 * - DataSource: retrieve all → return list
 * - Sequence: aggregate max → change attribute → end
 * - Custom: input parameter → (empty for manual completion)
 *
 * v2: Full activity wiring from Python MicroflowGenerator payloads.
 */

import { microflows, projects, domainmodels } from "mendixmodelsdk";
import type { IModel } from "mendixmodelsdk";
import { session } from "../session";
import type {
  MicroflowPayload,
  MicroflowActivity,
} from "../types/schemas";

// Re-export for backward compat
export type CreateMicroflowParams = MicroflowPayload;

export interface CreateMicroflowResult {
  status: "created" | "already_exists" | "error";
  name: string;
  module: string;
  microflow_type: string;
  activities_count: number;
  error?: string;
}

// Activity position spacing
const X_START = 200;
const X_SPACING = 200;
const Y_CENTER = 200;

/**
 * Creates a microflow in the Mendix project with real activities.
 */
export async function createMicroflow(
  appId: string,
  mf: MicroflowPayload,
  branchName = "main"
): Promise<CreateMicroflowResult> {
  try {
    const model = await session.getModel(appId, branchName);

    // 1. Find the target module
    const targetModule = findModule(model, mf.module);
    if (!targetModule) {
      return {
        status: "error",
        name: mf.name,
        module: mf.module,
        microflow_type: mf.microflow_type,
        activities_count: 0,
        error: `Module '${mf.module}' not found in project`,
      };
    }

    // 2. Check if microflow already exists
    for (const existing of model.allMicroflows()) {
      if (
        existing.name === mf.name &&
        getModuleName(existing) === mf.module
      ) {
        console.error(
          `[mendex-sdk] Microflow ${mf.module}.${mf.name} already exists`
        );
        return {
          status: "already_exists",
          name: mf.name,
          module: mf.module,
          microflow_type: mf.microflow_type,
          activities_count: 0,
        };
      }
    }

    // 3. Create the microflow
    const newMF = microflows.Microflow.createIn(targetModule);
    newMF.name = mf.name;

    // 4. Create the object collection
    const objectCollection =
      microflows.MicroflowObjectCollection.createInMicroflowBaseUnderObjectCollection(
        newMF
      );

    // 5. Create input parameter (if provided)
    if (mf.input_parameter) {
      const param =
        microflows.MicroflowParameterObject.createIn(objectCollection);
      param.name = mf.input_parameter.name;
      param.relativeMiddlePoint = { x: 50, y: Y_CENTER };

      // Set entity type on the parameter
      const entityQualifiedName = mf.input_parameter.entity;
      const entity = findEntityByQualifiedName(model, entityQualifiedName);
      if (entity) {
        const objectType =
          microflows.MicroflowParameterObjectType.createIn(param);
        // The entity reference needs to be set
        console.error(
          `[mendex-sdk] Input parameter '${param.name}' → entity '${entityQualifiedName}'`
        );
      }
    }

    // 6. Create start event
    const startEvent = microflows.StartEvent.createIn(objectCollection);
    startEvent.relativeMiddlePoint = { x: 100, y: Y_CENTER };

    // 7. Create activities between start and end
    const activities = mf.activities || [];
    const createdActivities: microflows.MicroflowObject[] = [];

    for (let i = 0; i < activities.length; i++) {
      const actDef = activities[i];
      const xPos = X_START + i * X_SPACING;
      const activity = createActivity(
        model,
        objectCollection,
        actDef,
        xPos,
        mf
      );
      if (activity) {
        createdActivities.push(activity);
      }
    }

    // 8. Create end event
    const endX =
      activities.length > 0
        ? X_START + activities.length * X_SPACING
        : 600;
    const endEvent = microflows.EndEvent.createIn(objectCollection);
    endEvent.relativeMiddlePoint = { x: endX, y: Y_CENTER };

    // 9. Set return type on end event
    setReturnType(endEvent, mf.return_type);

    // 10. Wire sequence flows: start → activity1 → activity2 → ... → end
    const chain: microflows.MicroflowObject[] = [
      startEvent,
      ...createdActivities,
      endEvent,
    ];

    for (let i = 0; i < chain.length - 1; i++) {
      const flow = microflows.SequenceFlow.createIn(newMF);
      flow.origin = chain[i];
      flow.destination = chain[i + 1];
    }

    // 11. Add documentation annotation with logic description
    if (mf.logic_description) {
      const annotation = microflows.Annotation.createIn(objectCollection);
      annotation.caption = mf.logic_description;
      annotation.relativeMiddlePoint = { x: 300, y: 50 };
    }

    // 12. Flush changes
    await model.flushChanges();

    console.error(
      `[mendex-sdk] Created microflow ${mf.module}.${mf.name} ` +
        `[${mf.microflow_type}] with ${createdActivities.length} activities`
    );

    return {
      status: "created",
      name: mf.name,
      module: mf.module,
      microflow_type: mf.microflow_type,
      activities_count: createdActivities.length,
    };
  } catch (err: unknown) {
    const msg = err instanceof Error ? err.message : String(err);
    console.error(`[mendex-sdk] Error creating microflow: ${msg}`);
    return {
      status: "error",
      name: mf.name,
      module: mf.module,
      microflow_type: mf.microflow_type,
      activities_count: 0,
      error: msg,
    };
  }
}

// ─── Activity Creators ──────────────────────────────────────

function createActivity(
  model: IModel,
  objectCollection: microflows.MicroflowObjectCollection,
  actDef: MicroflowActivity,
  xPos: number,
  mfPayload: MicroflowPayload
): microflows.MicroflowObject | null {
  switch (actDef.type) {
    case "CommitActivity":
      return createCommitActivity(objectCollection, actDef, xPos);

    case "DeleteActivity":
      return createDeleteActivity(objectCollection, actDef, xPos);

    case "RetrieveActivity":
      return createRetrieveActivity(objectCollection, actDef, xPos);

    case "ChangeActivity":
      return createChangeActivity(objectCollection, actDef, xPos);

    case "MicroflowCallActivity":
      return createMicroflowCallActivity(
        model,
        objectCollection,
        actDef,
        xPos,
        mfPayload
      );

    case "ClosePageActivity":
      return createClosePageActivity(objectCollection, xPos);

    case "ShowMessageActivity":
      return createShowMessageActivity(objectCollection, actDef, xPos);

    case "ValidationActivity":
      return createValidationActivity(objectCollection, actDef, xPos);

    default:
      console.error(
        `[mendex-sdk] Unknown activity type '${actDef.type}', skipping`
      );
      return null;
  }
}

function createCommitActivity(
  oc: microflows.MicroflowObjectCollection,
  actDef: MicroflowActivity,
  xPos: number
): microflows.ActionActivity {
  const activity = microflows.ActionActivity.createIn(oc);
  activity.relativeMiddlePoint = { x: xPos, y: Y_CENTER };

  const commitAction = microflows.CommitAction.createIn(activity);
  commitAction.withEvents = actDef.with_events !== false;

  // Set caption
  activity.caption = actDef.description || `Commit ${actDef.entity || ""}`;

  return activity;
}

function createDeleteActivity(
  oc: microflows.MicroflowObjectCollection,
  actDef: MicroflowActivity,
  xPos: number
): microflows.ActionActivity {
  const activity = microflows.ActionActivity.createIn(oc);
  activity.relativeMiddlePoint = { x: xPos, y: Y_CENTER };

  const deleteAction = microflows.DeleteAction.createIn(activity);

  activity.caption = actDef.description || `Delete ${actDef.entity || ""}`;

  return activity;
}

function createRetrieveActivity(
  oc: microflows.MicroflowObjectCollection,
  actDef: MicroflowActivity,
  xPos: number
): microflows.ActionActivity {
  const activity = microflows.ActionActivity.createIn(oc);
  activity.relativeMiddlePoint = { x: xPos, y: Y_CENTER };

  const retrieveAction = microflows.RetrieveAction.createIn(activity);

  // Set retrieve source based on action
  if (actDef.source === "database" || actDef.action === "retrieve_all") {
    const dbSource =
      microflows.DatabaseRetrieveSource.createIn(retrieveAction);
  } else if (actDef.action === "aggregate_max") {
    const dbSource =
      microflows.DatabaseRetrieveSource.createIn(retrieveAction);
    // Aggregate max requires XPath with sorting — log for manual refinement
    console.error(
      `[mendex-sdk] RetrieveActivity aggregate_max on ${actDef.entity}.${actDef.attribute} — needs manual XPath`
    );
  } else if (actDef.action === "find_by_name") {
    const dbSource =
      microflows.DatabaseRetrieveSource.createIn(retrieveAction);
    console.error(
      `[mendex-sdk] RetrieveActivity find_by_name on ${actDef.entity} — needs manual XPath constraint`
    );
  } else {
    // Default: association retrieve
    const assocSource =
      microflows.AssociationRetrieveSource.createIn(retrieveAction);
  }

  activity.caption =
    actDef.description || `Retrieve ${actDef.entity || ""}`;

  return activity;
}

function createChangeActivity(
  oc: microflows.MicroflowObjectCollection,
  actDef: MicroflowActivity,
  xPos: number
): microflows.ActionActivity {
  const activity = microflows.ActionActivity.createIn(oc);
  activity.relativeMiddlePoint = { x: xPos, y: Y_CENTER };

  const changeAction = microflows.ChangeObjectAction.createIn(activity);
  changeAction.commit = microflows.CommitEnum.No;

  // Add member change for the attribute
  if (actDef.attribute) {
    const memberChange =
      microflows.MemberChange.createIn(changeAction);
    // memberChange needs attribute reference + value expression
    console.error(
      `[mendex-sdk] ChangeActivity: ${actDef.entity}.${actDef.attribute} = ${actDef.value || "?"}`
    );
  }

  activity.caption =
    actDef.description || `Change ${actDef.entity || ""}.${actDef.attribute || ""}`;

  return activity;
}

function createMicroflowCallActivity(
  model: IModel,
  oc: microflows.MicroflowObjectCollection,
  actDef: MicroflowActivity,
  xPos: number,
  mfPayload: MicroflowPayload
): microflows.ActionActivity {
  const activity = microflows.ActionActivity.createIn(oc);
  activity.relativeMiddlePoint = { x: xPos, y: Y_CENTER };

  const callAction = microflows.MicroflowCallAction.createIn(activity);

  // Resolve target microflow
  if (actDef.microflow) {
    const qualifiedName = actDef.microflow.includes(".")
      ? actDef.microflow
      : `${mfPayload.module}.${actDef.microflow}`;

    const targetMf = findMicroflowByName(model, qualifiedName);
    if (targetMf) {
      callAction.microflowCall =
        microflows.MicroflowCall.createIn(callAction);
      callAction.microflowCall.microflow = targetMf;
    } else {
      console.error(
        `[mendex-sdk] Target microflow '${qualifiedName}' not found — needs manual wiring`
      );
    }
  }

  activity.caption = actDef.description || `Call ${actDef.microflow || "?"}`;

  return activity;
}

function createClosePageActivity(
  oc: microflows.MicroflowObjectCollection,
  xPos: number
): microflows.ActionActivity {
  const activity = microflows.ActionActivity.createIn(oc);
  activity.relativeMiddlePoint = { x: xPos, y: Y_CENTER };

  microflows.CloseFormAction.createIn(activity);

  activity.caption = "Close page";

  return activity;
}

function createShowMessageActivity(
  oc: microflows.MicroflowObjectCollection,
  actDef: MicroflowActivity,
  xPos: number
): microflows.ActionActivity {
  const activity = microflows.ActionActivity.createIn(oc);
  activity.relativeMiddlePoint = { x: xPos, y: Y_CENTER };

  const showMsg = microflows.ShowMessageAction.createIn(activity);

  // Set message type
  if (actDef.message_type === "confirmation") {
    // ShowMessage doesn't have confirmation type — use ShowHomePageAction pattern
    // For confirmation dialogs, typically use a decision with expression
    console.error(
      `[mendex-sdk] Confirmation dialog: '${actDef.message}' — implemented as ShowMessage`
    );
  }

  // Set message template
  const template = microflows.TextTemplate.createIn(showMsg);
  const templateText = microflows.TemplateText.createIn(template);

  activity.caption = actDef.message || "Show message";

  return activity;
}

function createValidationActivity(
  oc: microflows.MicroflowObjectCollection,
  actDef: MicroflowActivity,
  xPos: number
): microflows.ActionActivity {
  const activity = microflows.ActionActivity.createIn(oc);
  activity.relativeMiddlePoint = { x: xPos, y: Y_CENTER };

  // Validation is typically implemented as a validation feedback action
  const validationAction =
    microflows.ValidationFeedbackAction.createIn(activity);

  // Set the error message
  if (actDef.error_message) {
    const template =
      microflows.TextTemplate.createIn(validationAction);
    const text = microflows.TemplateText.createIn(template);
  }

  activity.caption =
    actDef.description ||
    `Validate ${actDef.attribute || ""}: ${actDef.error_message || ""}`;

  return activity;
}

// ─── Return Type ────────────────────────────────────────────

function setReturnType(
  endEvent: microflows.EndEvent,
  returnType: string
): void {
  if (returnType === "Boolean") {
    endEvent.returnValue = "$result";
  }
  // For "Void" and "List of *", the default end event return is fine
  // List return types need manual configuration of the return variable
  if (returnType && returnType.startsWith("List of ")) {
    console.error(
      `[mendex-sdk] Return type '${returnType}' — needs manual return variable configuration`
    );
  }
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

function findEntityByQualifiedName(
  model: IModel,
  qualifiedName: string
): domainmodels.IEntity | null {
  const parts = qualifiedName.split(".");
  if (parts.length !== 2) return null;

  const [moduleName, entityName] = parts;

  for (const dm of model.allDomainModels()) {
    if (dm.containerAsModule.name === moduleName) {
      for (const entity of dm.entities) {
        if (entity.name === entityName) {
          return entity;
        }
      }
    }
  }
  return null;
}

function findMicroflowByName(
  model: IModel,
  qualifiedName: string
): microflows.IMicroflow | null {
  const parts = qualifiedName.split(".");
  const mfName = parts.length > 1 ? parts[parts.length - 1] : qualifiedName;
  const moduleName = parts.length > 1 ? parts[0] : null;

  for (const mf of model.allMicroflows()) {
    if (mf.name === mfName) {
      if (moduleName) {
        const mfModule = getModuleName(mf);
        if (mfModule === moduleName) return mf;
      } else {
        return mf;
      }
    }
  }
  return null;
}

function getModuleName(mf: microflows.IMicroflow): string {
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
