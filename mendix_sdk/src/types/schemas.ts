/**
 * TypeScript types mirroring the Python IntermediateSchema.
 * Used for type-safe communication between Python agent and Node.js SDK bridge.
 *
 * v2: Expanded to cover full widget/activity payloads from Python generators.
 */

export type MendixDataType =
  | "String"
  | "Integer"
  | "Long"
  | "Decimal"
  | "Boolean"
  | "DateTime"
  | "Enumeration"
  | "HashedString"
  | "AutoNumber"
  | "Binary";

export type PageType = "Create" | "Edit" | "Overview" | "Config";
export type MicroflowType =
  | "Validation"
  | "Save"
  | "Delete"
  | "Custom"
  | "DataSource"
  | "Sequence";

export type AssociationType = "1-*" | "*-*" | "1-1";

export interface ValidationRule {
  type: string;
  params: Record<string, string | number>;
  error_message: string;
}

export interface Attribute {
  name: string;
  mendix_type: MendixDataType;
  label: string;
  required: boolean;
  validations: ValidationRule[];
  enum_values?: string[];
  default_value?: string;
}

export interface AccessRule {
  role: string;
  can_create: boolean;
  can_read: boolean;
  can_write: boolean;
  can_delete: boolean;
}

export interface Entity {
  name: string;
  module: string;
  attributes: Attribute[];
  access_rules: AccessRule[];
  is_persistable: boolean;
  is_lookup?: boolean;
  seed_values?: string[];
  has_sequential?: boolean;
  is_filter_entity?: boolean;
}

// ─── Widget Payload Types ───────────────────────────────────

export interface ConditionalVisibility {
  depends_on: string;
  operator: string;    // "equals" | "not_empty" | "contains"
  value?: string;
}

export interface WidgetPayload {
  widget_type: string;
  attribute?: string;
  label?: string;
  editable?: boolean;
  required?: boolean;
  section?: string;
  association?: string;
  display_attribute?: string;
  selectable_objects_source?: string;
  conditional_visibility?: ConditionalVisibility;
  is_filter?: boolean;
  filter_entity?: string;
  search_type?: string;       // "contains" | "equals"
  // NestedListView
  child_entity?: string;
  columns?: WidgetPayload[];
  buttons?: ButtonPayload[];
  // NavigationListItem
  target_page?: string;
}

export interface ButtonPayload {
  widget_type?: string;      // "ActionButton"
  label: string;
  button_type?: string;      // "Save", "Cancel", "Delete", "New", "Edit"
  action?: string;           // "call_microflow" | "show_page" | "close_page"
  microflow?: string;
  target_page?: string;
  style?: string;            // "Primary", "Danger", "Default"
  open_as?: string;          // "content" | "popup"
  placement?: string;        // "top" | "row"
}

export interface SectionPayload {
  name: string;
  order: number;
  attributes: string[];
}

// ─── Page Payload (full, from Python PageGenerator._build_page_data) ───

export interface PagePayload {
  name: string;
  page_type: PageType;
  entity: string;
  module: string;
  title: string;
  layout: string;
  widgets: WidgetPayload[];
  buttons?: ButtonPayload[];
  sections?: SectionPayload[];
  is_popup?: boolean;
  filter_entity?: string;
  enable_search_bar?: boolean;
}

// ─── Microflow Activity Types ───────────────────────────────

export interface MicroflowActivity {
  type: string;
  action: string;
  entity?: string;
  attribute?: string;
  value?: string;
  description?: string;
  microflow?: string;
  message?: string;
  message_type?: string;
  error_message?: string;
  params?: Record<string, unknown>;
  source?: string;
  with_events?: boolean;
}

export interface MicroflowInputParameter {
  name: string;
  entity: string;       // qualified: "Module.Entity"
}

export interface MicroflowPayload {
  name: string;
  microflow_type: MicroflowType;
  entity: string;
  module: string;
  logic_description: string;
  input_parameter?: MicroflowInputParameter;
  activities: MicroflowActivity[];
  return_type: string;  // "Boolean" | "Void" | "List of Entity"
  return_entity?: string;
}

// ─── Association Payload ────────────────────────────────────

export interface AssociationPayload {
  name: string;
  parent_entity: string;
  child_entity: string;
  association_type: AssociationType;
  module: string;
  owner?: string;            // "default" | "both"
  cascade_delete?: boolean;
  is_lookup?: boolean;
}

// ─── Legacy aliases (backward compat) ───────────────────────

export type Page = PagePayload;
export type Microflow = MicroflowPayload;

export interface IntermediateSchema {
  source: "excel" | "figma";
  source_file?: string;
  entities: Entity[];
  pages: PagePayload[];
  microflows: MicroflowPayload[];
}
