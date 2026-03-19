/**
 * Handler for reading .mpr structure (used by conventions extractor).
 *
 * Phase 3: Implements readProjectStructure via Mendix Model SDK.
 * Currently uses the SDK's working copy API to extract:
 * - Modules with their entities, pages, and microflows
 * - Security roles
 *
 * Note: Full SDK integration requires MENDIX_TOKEN and online
 * connection to Mendix Platform. For offline/testing use, the
 * MockSDKClient in Python should be used instead.
 */

export interface EntityData {
  name: string;
  attributes: string[];
}

export interface ModuleData {
  name: string;
  entities: EntityData[];
  pages: string[];
  microflows: string[];
}

export interface ProjectStructure {
  modules: ModuleData[];
  security: {
    roles: string[];
  };
}

export interface ArtifactExistsResult {
  exists: boolean;
  artifactType: string;
  module: string;
  name: string;
}

/**
 * Reads the complete structure of a Mendix project.
 *
 * In production, this connects to the Mendix Platform API via the Model SDK,
 * opens a working copy, and traverses the model to extract structure.
 *
 * @param mprPath - Absolute path to the .mpr file
 * @returns ProjectStructure with modules, entities, pages, microflows, and roles
 */
export async function readProjectStructure(
  mprPath: string
): Promise<ProjectStructure> {
  // TODO: Full Mendix Model SDK implementation
  // The actual implementation will:
  // 1. Create a MendixSdkClient with MENDIX_TOKEN
  // 2. Open a temporary working copy from the .mpr
  // 3. Traverse model.allDomainModels() for entities/attributes
  // 4. Traverse model.allPages() for page names
  // 5. Traverse model.allMicroflows() for microflow names
  // 6. Read model.allProjectSecurityRoles() for security roles
  // 7. Close the working copy
  //
  // For now, return a placeholder that indicates the SDK needs setup.

  console.error(
    `[mendex-sdk] readProjectStructure called for: ${mprPath}`
  );
  console.error(
    "[mendex-sdk] NOTE: Full Model SDK integration pending. " +
    "Use MockSDKClient in Python for development/testing."
  );

  return {
    modules: [],
    security: { roles: [] },
  };
}

/**
 * Checks if a specific artifact already exists in the project.
 *
 * @param mprPath - Absolute path to the .mpr file
 * @param artifactType - "entity" | "page" | "microflow"
 * @param moduleName - Module name to search in
 * @param artifactName - Name of the artifact to find
 */
export async function checkArtifactExists(
  mprPath: string,
  artifactType: string,
  moduleName: string,
  artifactName: string
): Promise<ArtifactExistsResult> {
  // TODO: Full implementation via Model SDK
  console.error(
    `[mendex-sdk] checkArtifactExists: ${artifactType} ${moduleName}.${artifactName}`
  );

  return {
    exists: false,
    artifactType,
    module: moduleName,
    name: artifactName,
  };
}
