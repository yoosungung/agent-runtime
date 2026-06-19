export type SourceKind = "agent" | "mcp";

/** Primary action on list pages */
export function listNewButtonLabel(kind: SourceKind): string {
  return kind === "agent" ? "+ New Agent" : "+ New MCP";
}

export function listNewImageButtonLabel(kind: SourceKind): string {
  return kind === "agent" ? "+ New Agent Image" : "+ New MCP Image";
}

export const listNewUserButtonLabel = "+ New User";

/** Form page titles */
export function newPageTitle(
  tier: "agent" | "bundle" | "container",
  kind: SourceKind,
): string {
  switch (tier) {
    case "agent":
      return "New Agent";
    case "bundle":
      return kind === "agent" ? "New Bundle Agent" : "New Bundle MCP";
    case "container":
      return kind === "agent" ? "New Agent Image" : "New MCP Image";
  }
}

/** Form submit buttons */
export function createSubmitLabel(kind: SourceKind): string {
  return kind === "agent" ? "Create Agent" : "Create MCP";
}

export function uploadSubmitLabel(kind: SourceKind): string {
  return kind === "agent" ? "Upload Agent" : "Upload MCP";
}

export const deployImageSubmitLabel = "Deploy Image";
export const createUserSubmitLabel = "Create User";
export const createUserPendingLabel = "Creating User…";

export function createSubmitPendingLabel(kind: SourceKind): string {
  return kind === "agent" ? "Creating Agent…" : "Creating MCP…";
}

export function uploadSubmitPendingLabel(kind: SourceKind): string {
  return kind === "agent" ? "Uploading Agent…" : "Uploading MCP…";
}

export const deployImagePendingLabel = "Deploying Image…";
