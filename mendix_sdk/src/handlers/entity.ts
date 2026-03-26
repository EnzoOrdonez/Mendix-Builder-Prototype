/**
 * Handler for entity/domain model operations via Mendix Model SDK.
 *
 * Creates entities with attributes and access rules in the online
 * working copy via the Platform SDK.
 */

import { domainmodels, security } from "mendixmodelsdk";
import type { IModel } from "mendixmodelsdk";
import { session } from "../session";
import type { Entity, Attribute, MendixDataType } from "../types/schemas";

export interface CreateEntityResult {
  status: "created" | "already_exists" | "error";
  name: string;
  module: string;
  attributes_count: number;
  access_rules_count: number;
  error?: string;
}

/**
 * Creates an entity with attributes and access rules.
 *
 * @param appId - Mendix App ID
 * @param entity - Entity definition from IntermediateSchema
 * @param branchName - Branch (default: "main")
 */
export async function createEntity(
  appId: string,
  entity: Entity,
  branchName = "main"
): Promise<CreateEntityResult> {
  try {
    const model = await session.getModel(appId, branchName);

    // 1. Find the target module's domain model
    const targetDM = findDomainModel(model, entity.module);
    if (!targetDM) {
      return {
        status: "error",
        name: entity.name,
        module: entity.module,
        attributes_count: 0,
        access_rules_count: 0,
        error: `Module '${entity.module}' not found in project`,
      };
    }

    // Load the full domain model
    const dm = await targetDM.load();

    // 2. Check if entity already exists
    for (const existing of dm.entities) {
      if (existing.name === entity.name) {
        console.error(
          `[mendex-sdk] Entity ${entity.module}.${entity.name} already exists`
        );
        return {
          status: "already_exists",
          name: entity.name,
          module: entity.module,
          attributes_count: 0,
          access_rules_count: 0,
        };
      }
    }

    // 3. Create the entity
    const newEntity = domainmodels.Entity.createIn(dm);
    newEntity.name = entity.name;

    // 4. Set generalization (no parent = NoGeneralization)
    const noGen = domainmodels.NoGeneralization.createIn(newEntity);
    noGen.persistable = entity.is_persistable !== false; // default true
    noGen.hasChangedDate = true;
    noGen.hasCreatedDate = true;
    noGen.hasOwner = true;
    noGen.hasChangedBy = true;

    // 5. Create attributes
    for (const attrDef of entity.attributes) {
      createAttribute(model, newEntity, attrDef);
    }

    // 6. Create access rules
    for (const ruleDef of entity.access_rules) {
      createAccessRule(model, newEntity, ruleDef, entity.module);
    }

    // Flush changes to server
    await model.flushChanges();

    console.error(
      `[mendex-sdk] Created entity ${entity.module}.${entity.name} ` +
      `(${entity.attributes.length} attrs, ${entity.access_rules.length} rules)`
    );

    return {
      status: "created",
      name: entity.name,
      module: entity.module,
      attributes_count: entity.attributes.length,
      access_rules_count: entity.access_rules.length,
    };
  } catch (err: unknown) {
    const msg = err instanceof Error ? err.message : String(err);
    console.error(`[mendex-sdk] Error creating entity: ${msg}`);
    return {
      status: "error",
      name: entity.name,
      module: entity.module,
      attributes_count: 0,
      access_rules_count: 0,
      error: msg,
    };
  }
}

/**
 * Reads entities from a specific module.
 */
export async function readEntities(
  appId: string,
  moduleName: string,
  branchName = "main"
): Promise<Entity[]> {
  const model = await session.getModel(appId, branchName);
  const targetDM = findDomainModel(model, moduleName);
  if (!targetDM) return [];

  const dm = await targetDM.load();
  const entities: Entity[] = [];

  for (const entity of dm.entities) {
    const loaded = await entity.load();
    const attrs: Attribute[] = loaded.attributes.map((attr) => ({
      name: attr.name,
      mendix_type: mapAttributeTypeBack(attr.type),
      label: attr.name, // SDK doesn't store label separately
      required: false, // Would need to check validation rules
      validations: [],
    }));

    entities.push({
      name: entity.name,
      module: moduleName,
      attributes: attrs,
      access_rules: [],
      is_persistable: true,
    });
  }

  return entities;
}

// --- Internal helpers ---

function findDomainModel(
  model: IModel,
  moduleName: string
): domainmodels.IDomainModel | null {
  for (const dm of model.allDomainModels()) {
    if (dm.containerAsModule.name === moduleName) {
      return dm;
    }
  }
  return null;
}

/**
 * Creates an attribute on the entity with the correct type.
 */
function createAttribute(
  model: IModel,
  entity: domainmodels.Entity,
  attrDef: Attribute
): void {
  const attr = domainmodels.Attribute.createIn(entity);
  attr.name = attrDef.name;

  // Set type based on mendix_type
  setAttributeType(attr, attrDef);
}

/**
 * Sets the correct AttributeType on an attribute based on the schema definition.
 */
function setAttributeType(
  attr: domainmodels.Attribute,
  attrDef: Attribute
): void {
  switch (attrDef.mendix_type) {
    case "String":
      domainmodels.StringAttributeType.createIn(attr);
      break;
    case "Integer":
      domainmodels.IntegerAttributeType.createIn(attr);
      break;
    case "Long":
      domainmodels.LongAttributeType.createIn(attr);
      break;
    case "Decimal":
      domainmodels.DecimalAttributeType.createIn(attr);
      break;
    case "Boolean":
      domainmodels.BooleanAttributeType.createIn(attr);
      break;
    case "DateTime":
      domainmodels.DateTimeAttributeType.createIn(attr);
      break;
    case "AutoNumber":
      domainmodels.AutoNumberAttributeType.createIn(attr);
      break;
    case "HashedString":
      domainmodels.HashedStringAttributeType.createIn(attr);
      break;
    case "Enumeration":
      // Enumeration requires a reference to an existing enumeration
      // For now, create as String and log a warning
      console.error(
        `[mendex-sdk] Warning: Enumeration type for ${attr.name} — ` +
        `creating as String. Enum reference must be set manually.`
      );
      domainmodels.StringAttributeType.createIn(attr);
      break;
    default:
      // Fallback to String
      domainmodels.StringAttributeType.createIn(attr);
      break;
  }
}

/**
 * Creates an access rule on the entity.
 */
function createAccessRule(
  model: IModel,
  entity: domainmodels.Entity,
  ruleDef: { role: string; can_create: boolean; can_read: boolean; can_write: boolean; can_delete: boolean },
  moduleName: string
): void {
  const rule = domainmodels.AccessRule.createInEntityUnderAccessRules(entity);
  rule.allowCreate = ruleDef.can_create;
  rule.allowDelete = ruleDef.can_delete;

  // Set default member access based on read/write permissions
  if (ruleDef.can_write) {
    rule.defaultMemberAccessRights = domainmodels.MemberAccessRights.ReadWrite;
  } else if (ruleDef.can_read) {
    rule.defaultMemberAccessRights = domainmodels.MemberAccessRights.ReadOnly;
  } else {
    rule.defaultMemberAccessRights = domainmodels.MemberAccessRights.None;
  }

  // Try to find and link the module role
  const moduleRole = findModuleRole(model, moduleName, ruleDef.role);
  if (moduleRole) {
    rule.moduleRoles.push(moduleRole);
  } else {
    console.error(
      `[mendex-sdk] Warning: Module role '${ruleDef.role}' not found in module '${moduleName}'`
    );
  }
}

/**
 * Finds a module role by name within a specific module.
 */
function findModuleRole(
  model: IModel,
  moduleName: string,
  roleName: string
): security.IModuleRole | null {
  for (const ms of model.allModuleSecurities()) {
    // Module security's container should be the target module
    const mod = ms.containerAsModule;
    if (mod.name === moduleName) {
      const loaded = ms as security.ModuleSecurity;
      for (const role of loaded.moduleRoles) {
        if (role.name === roleName) {
          return role;
        }
      }
    }
  }
  return null;
}

/**
 * Maps an SDK AttributeType back to our MendixDataType string.
 */
function mapAttributeTypeBack(attrType: domainmodels.AttributeType): MendixDataType {
  const typeName = attrType.structureTypeName;
  if (typeName.includes("String")) return "String";
  if (typeName.includes("Integer") && !typeName.includes("AutoNumber")) return "Integer";
  if (typeName.includes("Long")) return "Long";
  if (typeName.includes("Decimal")) return "Decimal";
  if (typeName.includes("Boolean")) return "Boolean";
  if (typeName.includes("DateTime")) return "DateTime";
  if (typeName.includes("AutoNumber")) return "AutoNumber";
  if (typeName.includes("HashedString")) return "HashedString";
  if (typeName.includes("Enumeration")) return "Enumeration";
  return "String";
}
