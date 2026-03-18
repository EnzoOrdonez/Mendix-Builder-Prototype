/**
 * TypeScript types mirroring the Python IntermediateSchema.
 * Used for type-safe communication between Python agent and Node.js SDK bridge.
 *
 * Phase 0: Type definitions only. Used by handlers in later phases.
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
  | "AutoNumber";

export type PageType = "Create" | "Edit" | "Overview";
export type MicroflowType = "Validation" | "Save" | "Delete" | "Custom";

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
}

export interface Page {
  name: string;
  page_type: PageType;
  entity: string;
  module: string;
  title?: string;
  layout: string;
}

export interface Microflow {
  name: string;
  microflow_type: MicroflowType;
  entity: string;
  module: string;
  logic_description: string;
}

export interface IntermediateSchema {
  source: "excel" | "figma";
  source_file?: string;
  entities: Entity[];
  pages: Page[];
  microflows: Microflow[];
}
