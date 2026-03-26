/**
 * Session manager for Mendix Platform SDK working copies.
 *
 * Manages the lifecycle of a temporary working copy:
 * - Creates working copy on first operation
 * - Caches the IModel for reuse across operations
 * - Commits and closes when done
 *
 * Requires:
 * - MENDIX_TOKEN env var (Personal Access Token)
 * - APP_ID passed via JSON-RPC params or MENDIX_APP_ID env var
 */

import { MendixPlatformClient, setPlatformConfig } from "mendixplatformsdk";
import type { IModel } from "mendixmodelsdk";

export interface SessionInfo {
  appId: string;
  branchName: string;
  workingCopyId: string;
}

/**
 * Singleton session manager. One working copy per app at a time.
 */
class SessionManager {
  private model: IModel | null = null;
  private sessionInfo: SessionInfo | null = null;
  private commitFn: ((branch?: string) => Promise<void>) | null = null;
  private initialized = false;

  /**
   * Initialize the Platform SDK with the MENDIX_TOKEN.
   * Called once on first use.
   */
  private ensureConfig(): void {
    if (this.initialized) return;

    const token = process.env.MENDIX_TOKEN;
    if (!token) {
      throw new Error(
        "MENDIX_TOKEN env var not set. " +
        "Get a Personal Access Token from https://warden.mendix.com"
      );
    }

    setPlatformConfig({ mendixToken: token });
    this.initialized = true;
    console.error("[mendex-sdk] Platform SDK configured with MENDIX_TOKEN");
  }

  /**
   * Get or create a working copy model for the given app.
   *
   * If a working copy is already open for the same app, returns the cached model.
   * Otherwise creates a new temporary working copy.
   */
  async getModel(appId: string, branchName = "main"): Promise<IModel> {
    // Return cached model if same app
    if (
      this.model !== null &&
      this.sessionInfo !== null &&
      this.sessionInfo.appId === appId &&
      this.sessionInfo.branchName === branchName
    ) {
      return this.model;
    }

    // Close existing session if different app
    if (this.model !== null) {
      await this.close();
    }

    this.ensureConfig();

    console.error(
      `[mendex-sdk] Creating working copy for app ${appId} branch ${branchName}...`
    );

    const client = new MendixPlatformClient();
    const app = client.getApp(appId);
    const workingCopy = await app.createTemporaryWorkingCopy(branchName);

    console.error(
      `[mendex-sdk] Working copy created: ${workingCopy.workingCopyId}`
    );

    this.model = await workingCopy.openModel();

    console.error("[mendex-sdk] Model opened successfully");

    this.sessionInfo = {
      appId,
      branchName,
      workingCopyId: workingCopy.workingCopyId,
    };

    // Store commit function with closure over workingCopy
    this.commitFn = async (branch?: string) => {
      if (this.model) {
        await this.model.flushChanges();
      }
      await workingCopy.commitToRepository(branch ?? branchName);
    };

    return this.model;
  }

  /**
   * Commit all pending changes to the repository.
   */
  async commit(branchName?: string): Promise<void> {
    if (!this.commitFn || !this.sessionInfo) {
      throw new Error("No active session to commit");
    }

    const branch = branchName ?? this.sessionInfo.branchName;
    console.error(`[mendex-sdk] Committing to branch ${branch}...`);

    await this.commitFn(branch);
    console.error("[mendex-sdk] Commit successful");
  }

  /**
   * Get current session info.
   */
  getSessionInfo(): SessionInfo | null {
    return this.sessionInfo;
  }

  /**
   * Check if a session is active.
   */
  isActive(): boolean {
    return this.model !== null && this.sessionInfo !== null;
  }

  /**
   * Close the current session (does NOT commit).
   */
  async close(): Promise<void> {
    this.model = null;
    this.sessionInfo = null;
    this.commitFn = null;
    console.error("[mendex-sdk] Session closed");
  }
}

// Singleton instance
export const session = new SessionManager();
