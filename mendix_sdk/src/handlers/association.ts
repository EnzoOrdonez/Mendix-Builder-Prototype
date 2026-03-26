/**
 * Handler for association operations via Mendix Model SDK.
 *
 * Creates associations between entities in the domain model:
 * - Reference (1-*): Parent has one child reference
 * - ReferenceSet (*-*): Many-to-many
 * - Reference (1-1): One-to-one (same as Reference with uniqueness)
 *
 * Supports:
 * - Owner configuration (default / both)
 * - Delete behavior (cascade / prevent)
 * - Lookup association flag (for tabla maestra pattern)
 */

import { domainmodels } from "mendixmodelsdk";
import type { IModel } from "mendixmodelsdk";
import { session } from "../session";
import type { AssociationPayload } from "../types/schemas";

// Re-export for backward compat
export type CreateAssociationParams = AssociationPayload;

export interface CreateAssociationResult {
  status: "created" | "already_exists" | "error";
  name: string;
  parent_entity: string;
  child_entity: string;
  association_type: string;
  module: string;
  error?: string;
}

/**
 * Creates an association between two entities in the domain model.
 */
export async function createAssociation(
  appId: string,
  assoc: AssociationPayload,
  branchName = "main"
): Promise<CreateAssociationResult> {
  try {
    const model = await session.getModel(appId, branchName);

    // 1. Find the domain model for the module
    const dm = findDomainModel(model, assoc.module);
    if (!dm) {
      return {
        status: "error",
        name: assoc.name,
        parent_entity: assoc.parent_entity,
        child_entity: assoc.child_entity,
        association_type: assoc.association_type,
        module: assoc.module,
        error: `Module '${assoc.module}' not found in project`,
      };
    }

    // Load the full domain model
    const loadedDM = await dm.load();

    // 2. Find parent and child entities
    const parentEntity = findEntity(loadedDM, assoc.parent_entity);
    const childEntity = findEntity(loadedDM, assoc.child_entity);

    if (!parentEntity) {
      return {
        status: "error",
        name: assoc.name,
        parent_entity: assoc.parent_entity,
        child_entity: assoc.child_entity,
        association_type: assoc.association_type,
        module: assoc.module,
        error: `Parent entity '${assoc.parent_entity}' not found in module '${assoc.module}'`,
      };
    }

    if (!childEntity) {
      return {
        status: "error",
        name: assoc.name,
        parent_entity: assoc.parent_entity,
        child_entity: assoc.child_entity,
        association_type: assoc.association_type,
        module: assoc.module,
        error: `Child entity '${assoc.child_entity}' not found in module '${assoc.module}'`,
      };
    }

    // 3. Check if association already exists
    for (const existing of loadedDM.associations) {
      if (existing.name === assoc.name) {
        console.error(
          `[mendex-sdk] Association ${assoc.module}.${assoc.name} already exists`
        );
        return {
          status: "already_exists",
          name: assoc.name,
          parent_entity: assoc.parent_entity,
          child_entity: assoc.child_entity,
          association_type: assoc.association_type,
          module: assoc.module,
        };
      }
    }

    // 4. Create the association
    const newAssoc = domainmodels.Association.createIn(loadedDM);
    newAssoc.name = assoc.name;
    newAssoc.parent = parentEntity;
    newAssoc.child = childEntity;

    // 5. Set association type
    if (assoc.association_type === "*-*") {
      newAssoc.type = domainmodels.AssociationType.ReferenceSet;
    } else {
      // 1-* and 1-1 both use Reference
      newAssoc.type = domainmodels.AssociationType.Reference;
    }

    // 6. Set owner
    if (assoc.owner === "both") {
      newAssoc.owner = domainmodels.AssociationOwner.Both;
    } else {
      newAssoc.owner = domainmodels.AssociationOwner.Default;
    }

    // 7. Set delete behavior
    if (assoc.cascade_delete) {
      newAssoc.deleteBehavior =
        domainmodels.DeletingBehavior.createIn(newAssoc);
      newAssoc.deleteBehavior.childDeleteBehavior =
        domainmodels.DeletionDeleteBehavior.createIn(
          newAssoc.deleteBehavior
        );
      newAssoc.deleteBehavior.parentDeleteBehavior =
        domainmodels.DeletionPreventDeleteBehavior.createIn(
          newAssoc.deleteBehavior
        );

      console.error(
        `[mendex-sdk] Association ${assoc.name}: cascade delete on parent → delete children`
      );
    }

    // 8. Flush changes
    await model.flushChanges();

    console.error(
      `[mendex-sdk] Created association ${assoc.module}.${assoc.name} ` +
        `(${assoc.parent_entity} ${assoc.association_type} ${assoc.child_entity})`
    );

    return {
      status: "created",
      name: assoc.name,
      parent_entity: assoc.parent_entity,
      child_entity: assoc.child_entity,
      association_type: assoc.association_type,
      module: assoc.module,
    };
  } catch (err: unknown) {
    const msg = err instanceof Error ? err.message : String(err);
    console.error(`[mendex-sdk] Error creating association: ${msg}`);
    return {
      status: "error",
      name: assoc.name,
      parent_entity: assoc.parent_entity,
      child_entity: assoc.child_entity,
      association_type: assoc.association_type,
      module: assoc.module,
      error: msg,
    };
  }
}

// ─── Helpers ────────────────────────────────────────────────

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

function findEntity(
  dm: domainmodels.DomainModel,
  entityName: string
): domainmodels.Entity | null {
  for (const entity of dm.entities) {
    if (entity.name === entityName) {
      return entity as domainmodels.Entity;
    }
  }
  return null;
}
