/**
 * JSON-RPC stdio server for Mendix Model SDK operations.
 *
 * This process is spawned by the Python agent and communicates via
 * stdin/stdout using JSON-RPC 2.0 protocol.
 *
 * Phase 0: Stub with echo handler. Full implementation in Phases 3, 8, 9.
 */

import * as readline from "readline";

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
  switch (req.method) {
    case "ping":
      return createResponse(req.id, { status: "ok", version: "0.1.0" });

    case "echo":
      return createResponse(req.id, req.params);

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

process.stderr.write("[mendex-sdk-bridge] Ready\n");
