/**
 * Handler for reading project structure via Mendix Platform SDK.
 *
 * Uses the Platform SDK to open a working copy and traverse the model
 * to extract modules, entities, pages, microflows, and security roles.
 *
 * Note: For offline/fast reads, the Python MprDirectReader is preferred.
 * This handler is used when the CompositeSDKClient needs online reads
 * or when operating without a local .mpr file.
 */

import { domainmodels, microflows, pages, security, projects } from "mendixmodelsdk";
import { session } from "../session";

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
 * Reads the complete structure of a Mendix project via Platform SDK.
 *
 * @param appId - The Mendix App ID (from Developer Portal)
 * @param branchName - Branch to read from (default: "main")
 * @returns ProjectStructure with modules, entities, pages, microflows, and roles
 */
export async function readProjectStructure(
  appId: string,
  branchName = "main"
): Promise<ProjectStructure> {
  const model = await session.getModel(appId, branchName);

  console.error("[mendex-sdk] Reading project structure...");

  // 1. Get all modules
  const allModules = model.allModules();
  const moduleDataList: ModuleData[] = [];

  for (const mod of allModules) {
    // Skip marketplace/system modules
    if (mod.fromAppStore) continue;

    const moduleName = mod.name;

    // 2. Get domain model → entities + attributes
    const domainModel = mod.domainModel;
    const loadedDM = await domainModel.load();
    const entities: EntityData[] = [];

    for (const entity of loadedDM.entities) {
      const loadedEntity = await entity.load();
      const attrs = loadedEntity.attributes.map(
        (attr: domainmodels.IAttribute) => attr.name
      );
      entities.push({ name: entity.name, attributes: attrs });
    }

    // 3. Get pages (traverse module folders)
    const modulePages: string[] = [];
    const moduleMicroflows: string[] = [];

    // Use model.allPages() and allMicroflows() filtered by module
    for (const page of model.allPages()) {
      if (getModuleName(page) === moduleName) {
        modulePages.push(page.name);
      }
    }

    for (const mf of model.allMicroflows()) {
      if (getModuleName(mf) === moduleName) {
        moduleMicroflows.push(mf.name);
      }
    }

    moduleDataList.push({
      name: moduleName,
      entities,
      pages: modulePages,
      microflows: moduleMicroflows,
    });
  }

  // 4. Get security roles
  const roles: string[] = [];
  const projectSecurities = model.allProjectSecurities();
  if (projectSecurities.length > 0) {
    const ps = await projectSecurities[0].load();
    for (const role of ps.userRoles) {
      roles.push(role.name);
    }
  }

  // Sort modules alphabetically
  moduleDataList.sort((a, b) => a.name.localeCompare(b.name));

  console.error(
    `[mendex-sdk] Read: ${moduleDataList.length} modules, ` +
    `${moduleDataList.reduce((s, m) => s + m.entities.length, 0)} entities, ` +
    `${moduleDataList.reduce((s, m) => s + m.pages.length, 0)} pages, ` +
    `${moduleDataList.reduce((s, m) => s + m.microflows.length, 0)} microflows, ` +
    `${roles.length} roles`
  );

  return { modules: moduleDataList, security: { roles } };
}

/**
 * Checks if a specific artifact already exists in the project.
 */
export async function checkArtifactExists(
  appId: string,
  artifactType: string,
  moduleName: string,
  artifactName: string,
  branchName = "main"
): Promise<ArtifactExistsResult> {
  const model = await session.getModel(appId, branchName);
  const qualifiedName = `${moduleName}.${artifactName}`;
  let exists = false;

  switch (artifactType) {
    case "entity": {
      // Search in domain models
      for (const dm of model.allDomainModels()) {
        if (dm.containerAsModule.name === moduleName) {
          for (const entity of dm.entities) {
            if (entity.name === artifactName) {
              exists = true;
              break;
            }
          }
          break;
        }
      }
      break;
    }
    case "page": {
      for (const page of model.allPages()) {
        if (page.name === artifactName && getModuleName(page) === moduleName) {
          exists = true;
          break;
        }
      }
      break;
    }
    case "microflow": {
      for (const mf of model.allMicroflows()) {
        if (mf.name === artifactName && getModuleName(mf) === moduleName) {
          exists = true;
          break;
        }
      }
      break;
    }
  }

  console.error(
    `[mendex-sdk] checkArtifactExists: ${artifactType} ${qualifiedName} → ${exists}`
  );

  return { exists, artifactType, module: moduleName, name: artifactName };
}

/**
 * Helper: get module name from a document (page, microflow, etc.)
 * by traversing the container hierarchy.
 */
function getModuleName(
  doc: pages.IPage | microflows.IMicroflow
): string {
  // Traverse up through FolderBase containers to find the Module
  let container: projects.IFolderBase = doc.containerAsFolderBase;
  while (container) {
    if ("fromAppStore" in container) {
      // This is a Module
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
