/**
 * JSON-RPC stdio server for Mendix Model SDK operations.
 *
 * This process is spawned by the Python agent and communicates via
 * stdin/stdout using JSON-RPC 2.0 protocol.
 *
 * Phase 0: Stub with echo handler.
 * Phase 3: Added readProjectStructure and checkArtifactExists.
 * Phase 8: Added createEntity.
 * Phase 9: Will add createPage, createMicroflow.
 */

import * as readline from "readline";
import {
  readProjectStructure,
  checkArtifactExists,
} from "./handlers/reader";
import { createEntity } from "./handlers/entity";
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

async function handleRequest(req: JsonRpcRequest): Promise<JsonRpcResponse> {
  const params = req.params || {};

  switch (req.method) {
    case "ping":
      return createResponse(req.id, { status: "ok", version: "0.8.0" });

    case "echo":
      return createResponse(req.id, params);

    case "readProjectStructure": {
      const mprPath = params.mprPath as string;
      if (!mprPath) {
        return createError(req.id, -32602, "Missing required param: mprPath");
      }
      try {
        const result = await readProjectStructure(mprPath);
        return createResponse(req.id, result);
      } catch (err: unknown) {
        const msg = err instanceof Error ? err.message : String(err);
        return createError(req.id, -32000, `readProjectStructure failed: ${msg}`);
      }
    }

    case "checkArtifactExists": {
      const mprPath2 = params.mprPath as string;
      const artifactType = params.artifactType as string;
      const moduleName = params.module as string;
      const name = params.name as string;
      if (!mprPath2 || !artifactType || !moduleName || !name) {
        return createError(
          req.id,
          -32602,
          "Missing required params: mprPath, artifactType, module, name"
        );
      }
      try {
        const result = await checkArtifactExists(
          mprPath2, artifactType, moduleName, name
        );
        return createResponse(req.id, result);
      } catch (err: unknown) {
        const msg = err instanceof Error ? err.message : String(err);
        return createError(req.id, -32000, `checkArtifactExists failed: ${msg}`);
      }
    }

    case "createEntity": {
      const mprPath3 = params.mprPath as string;
      const entityData = params.entity as Entity;
      if (!mprPath3 || !entityData) {
        return createError(
          req.id,
          -32602,
          "Missing required params: mprPath, entity"
        );
      }
      try {
        const result = await createEntity(mprPath3, entityData);
        return createResponse(req.id, result);
      } catch (err: unknown) {
        const msg = err instanceof Error ? err.message : String(err);
        return createError(req.id, -32000, `createEntity failed: ${msg}`);
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

process.stderr.write("[mendex-sdk-bridge] Ready (v0.8.0)\n");
