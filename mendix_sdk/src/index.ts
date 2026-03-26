/**
 * JSON-RPC stdio server for Mendix Model SDK operations.
 *
 * This process is spawned by the Python agent and communicates via
 * stdin/stdout using JSON-RPC 2.0 protocol.
 *
 * Environment variables:
 * - MENDIX_TOKEN: Personal Access Token (required for SDK operations)
 * - MENDIX_APP_ID: Default App ID (can be overridden per request)
 *
 * Methods:
 * - ping: Health check
 * - openSession: Create/reuse a working copy for an app
 * - readProjectStructure: Read modules/entities/pages/microflows/roles
 * - checkArtifactExists: Check if entity/page/microflow exists
 * - createEntity: Create entity with attributes and access rules
 * - createPage: Create page with layout
 * - createMicroflow: Create microflow with activities
 * - createAssociation: Create association between entities
 * - commitSession: Commit all changes to repository
 * - closeSession: Close working copy without committing
 */

import * as readline from "readline";
import {
  readProjectStructure,
  checkArtifactExists,
} from "./handlers/reader";
import { createEntity } from "./handlers/entity";
import { createPage, type CreatePageParams } from "./handlers/page";
import { createMicroflow, type CreateMicroflowParams } from "./handlers/microflow";
import { createAssociation, type CreateAssociationParams } from "./handlers/association";
import { session } from "./session";
import type { Entity } from "./types/schemas";

interface JsonRpcRequest {
  jsonrpc: "2.0";
  id: number | string;
  method: string;
  params?: Record<string, unknown>;
}

interface JsonRpcResponse {
  jsonrpc: "2.0";
  id: number | string;
  result?: unknown;
  error?: { code: number; message: string; data?: unknown };
}

function createResponse(
  id: number | string,
  result: unknown
): JsonRpcResponse {
  return { jsonrpc: "2.0", id, result };
}

function createError(
  id: number | string,
  code: number,
  message: string
): JsonRpcResponse {
  return { jsonrpc: "2.0", id, error: { code, message } };
}

/**
 * Resolve the App ID from params or env var.
 */
function resolveAppId(params: Record<string, unknown>): string | null {
  return (params.appId as string) || process.env.MENDIX_APP_ID || null;
}

/**
 * Resolve the branch name from params or default to "main".
 */
function resolveBranch(params: Record<string, unknown>): string {
  return (params.branchName as string) || "main";
}

async function handleRequest(req: JsonRpcRequest): Promise<JsonRpcResponse> {
  const params = req.params || {};

  switch (req.method) {
    case "ping":
      return createResponse(req.id, {
        status: "ok",
        version: "1.0.0",
        hasToken: !!process.env.MENDIX_TOKEN,
        defaultAppId: process.env.MENDIX_APP_ID || null,
        sessionActive: session.isActive(),
        sessionInfo: session.getSessionInfo(),
      });

    case "echo":
      return createResponse(req.id, params);

    case "openSession": {
      const appId = resolveAppId(params);
      if (!appId) {
        return createError(req.id, -32602, "Missing appId param or MENDIX_APP_ID env var");
      }
      const branch = resolveBranch(params);
      try {
        await session.getModel(appId, branch);
        return createResponse(req.id, {
          status: "ok",
          ...session.getSessionInfo(),
        });
      } catch (err: unknown) {
        const msg = err instanceof Error ? err.message : String(err);
        return createError(req.id, -32000, `openSession failed: ${msg}`);
      }
    }

    case "readProjectStructure": {
      const appId = resolveAppId(params);
      if (!appId) {
        return createError(req.id, -32602, "Missing appId param or MENDIX_APP_ID env var");
      }
      const branch = resolveBranch(params);
      try {
        const result = await readProjectStructure(appId, branch);
        return createResponse(req.id, result);
      } catch (err: unknown) {
        const msg = err instanceof Error ? err.message : String(err);
        return createError(req.id, -32000, `readProjectStructure failed: ${msg}`);
      }
    }

    case "checkArtifactExists": {
      const appId = resolveAppId(params);
      const artifactType = params.artifactType as string;
      const moduleName = params.module as string;
      const name = params.name as string;
      if (!appId || !artifactType || !moduleName || !name) {
        return createError(
          req.id,
          -32602,
          "Missing required params: appId (or MENDIX_APP_ID), artifactType, module, name"
        );
      }
      const branch = resolveBranch(params);
      try {
        const result = await checkArtifactExists(
          appId, artifactType, moduleName, name, branch
        );
        return createResponse(req.id, result);
      } catch (err: unknown) {
        const msg = err instanceof Error ? err.message : String(err);
        return createError(req.id, -32000, `checkArtifactExists failed: ${msg}`);
      }
    }

    case "createEntity": {
      const appId = resolveAppId(params);
      const entityData = params.entity as Entity;
      if (!appId || !entityData) {
        return createError(
          req.id,
          -32602,
          "Missing required params: appId (or MENDIX_APP_ID), entity"
        );
      }
      const branch = resolveBranch(params);
      try {
        const result = await createEntity(appId, entityData, branch);
        return createResponse(req.id, result);
      } catch (err: unknown) {
        const msg = err instanceof Error ? err.message : String(err);
        return createError(req.id, -32000, `createEntity failed: ${msg}`);
      }
    }

    case "createPage": {
      const appId = resolveAppId(params);
      const pageData = params.page as CreatePageParams;
      if (!appId || !pageData) {
        return createError(
          req.id,
          -32602,
          "Missing required params: appId (or MENDIX_APP_ID), page"
        );
      }
      const branch = resolveBranch(params);
      try {
        const result = await createPage(appId, pageData, branch);
        return createResponse(req.id, result);
      } catch (err: unknown) {
        const msg = err instanceof Error ? err.message : String(err);
        return createError(req.id, -32000, `createPage failed: ${msg}`);
      }
    }

    case "createMicroflow": {
      const appId = resolveAppId(params);
      const mfData = params.microflow as CreateMicroflowParams;
      if (!appId || !mfData) {
        return createError(
          req.id,
          -32602,
          "Missing required params: appId (or MENDIX_APP_ID), microflow"
        );
      }
      const branch = resolveBranch(params);
      try {
        const result = await createMicroflow(appId, mfData, branch);
        return createResponse(req.id, result);
      } catch (err: unknown) {
        const msg = err instanceof Error ? err.message : String(err);
        return createError(req.id, -32000, `createMicroflow failed: ${msg}`);
      }
    }

    case "createAssociation": {
      const appId = resolveAppId(params);
      const assocData = params.association as CreateAssociationParams;
      if (!appId || !assocData) {
        return createError(
          req.id,
          -32602,
          "Missing required params: appId (or MENDIX_APP_ID), association"
        );
      }
      const branch = resolveBranch(params);
      try {
        const result = await createAssociation(appId, assocData, branch);
        return createResponse(req.id, result);
      } catch (err: unknown) {
        const msg = err instanceof Error ? err.message : String(err);
        return createError(req.id, -32000, `createAssociation failed: ${msg}`);
      }
    }

    case "commitSession": {
      const branch = resolveBranch(params);
      const message = (params.message as string) || undefined;
      try {
        await session.commit(branch);
        return createResponse(req.id, {
          status: "committed",
          branch,
          message,
          ...session.getSessionInfo(),
        });
      } catch (err: unknown) {
        const msg = err instanceof Error ? err.message : String(err);
        return createError(req.id, -32000, `commitSession failed: ${msg}`);
      }
    }

    case "closeSession": {
      try {
        await session.close();
        return createResponse(req.id, { status: "closed" });
      } catch (err: unknown) {
        const msg = err instanceof Error ? err.message : String(err);
        return createError(req.id, -32000, `closeSession failed: ${msg}`);
      }
    }

    default:
      return createError(req.id, -32601, `Method not found: ${req.method}`);
  }
}

// --- Main: Read JSON-RPC from stdin, write to stdout ---
const rl = readline.createInterface({ input: process.stdin });

rl.on("line", async (line: string) => {
  try {
    const req = JSON.parse(line) as JsonRpcRequest;
    const res = await handleRequest(req);
    process.stdout.write(JSON.stringify(res) + "\n");
  } catch {
    const errorRes: JsonRpcResponse = {
      jsonrpc: "2.0",
      id: 0,
      error: { code: -32700, message: "Parse error" },
    };
    process.stdout.write(JSON.stringify(errorRes) + "\n");
  }
});

process.stderr.write("[mendex-sdk-bridge] Ready (v1.0.0)\n");
