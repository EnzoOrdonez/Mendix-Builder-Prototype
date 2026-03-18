/**
 * Handler for reading .mpr structure (used by conventions extractor).
 * Phase 0: Stub. Full implementation in Phase 3.
 */

export interface ProjectStructure {
  modules: Array<{
    name: string;
    entities: Array<{ name: string; attributes: string[] }>;
    pages: string[];
    microflows: string[];
  }>;
  security: {
    roles: string[];
  };
}

export async function readProjectStructure(
  _mprPath: string
): Promise<ProjectStructure> {
  // TODO: Implement via mendixmodelsdk in Phase 3
  return {
    modules: [],
    security: { roles: [] },
  };
}
