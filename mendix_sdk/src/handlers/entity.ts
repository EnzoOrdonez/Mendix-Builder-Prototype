/**
 * Handler for entity/domain model operations via Mendix Model SDK.
 *
 * Phase 0: Stub.
 * Phase 8: Full entity creation interface.
 *
 * Note: The actual Mendix Model SDK calls require a MENDIX_TOKEN and
 * online connection to the Mendix Platform. This handler defines the
 * interface and will be connected to the real SDK when available.
 */

import type { Entity, Attribute, AccessRule } from "../types/schemas";

/**
 * Result of creating an entity.
 */
export interface CreateEntityResult {
  status: "created" | "already_exists" | "error";
  name: string;
  module: string;
  attributes_count: number;
  access_rules_count: number;
  error?: string;
}

/**
 * Creates an entity with attributes and access rules in the .mpr.
 *
 * In production, this will:
 * 1. Open/reuse a working copy via MendixSdkClient
 * 2. Find or create the target module
 * 3. Create the entity with domainmodels.Entity.createIn()
 * 4. Add attributes with correct types via domainmodels.Attribute.createIn()
 * 5. Set up access rules via security module
 * 6. Commit the working copy
 *
 * @param mprPath - Absolute path to the .mpr file
 * @param entity - Entity definition from IntermediateSchema
 * @returns CreateEntityResult with status and details
 */
export async function createEntity(
  mprPath: string,
  entity: Entity
): Promise<CreateEntityResult> {
  // TODO: Connect to real Mendix Model SDK
  // The implementation will use:
  //   import { MendixSdkClient } from "mendixplatformsdk";
  //   import { domainmodels } from "mendixmodelsdk";
  //
  // Pseudo-code:
  //   const client = new MendixSdkClient(MENDIX_TOKEN);
  //   const project = client.getProject(APP_ID);
  //   const workingCopy = await project.createWorkingCopy();
  //   const module = workingCopy.model().findModuleByQualifiedName(entity.module);
  //   const domainModel = module.domainModel;
  //   const newEntity = domainmodels.Entity.createIn(domainModel);
  //   newEntity.name = entity.name;
  //   // ... add attributes, access rules
  //   await workingCopy.commit();

  console.error(
    `[mendex-sdk] createEntity: ${entity.module}.${entity.name} ` +
    `(${entity.attributes.length} attrs, ${entity.access_rules.length} rules)`
  );

  return {
    status: "created",
    name: entity.name,
    module: entity.module,
    attributes_count: entity.attributes.length,
    access_rules_count: entity.access_rules.length,
  };
}

/**
 * Reads entities from a specific module.
 *
 * @param mprPath - Absolute path to the .mpr file
 * @param moduleName - Module name to read from
 */
export async function readEntities(
  mprPath: string,
  moduleName: string
): Promise<Entity[]> {
  // TODO: Implement via mendixmodelsdk
  console.error(
    `[mendex-sdk] readEntities: ${moduleName} from ${mprPath}`
  );
  return [];
}
