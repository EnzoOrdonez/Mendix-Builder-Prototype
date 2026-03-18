/**
 * Handler for entity/domain model operations via Mendix Model SDK.
 * Phase 0: Stub. Full implementation in Phase 8.
 */

import type { Entity } from "../types/schemas";

export async function createEntity(_entity: Entity): Promise<{ status: string }> {
  // TODO: Implement via mendixmodelsdk in Phase 8
  return { status: "not_implemented" };
}

export async function readEntities(_moduleName: string): Promise<Entity[]> {
  // TODO: Implement via mendixmodelsdk in Phase 3 (conventions extractor)
  return [];
}
