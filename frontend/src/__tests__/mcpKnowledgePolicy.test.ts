import { describe, expect, it } from "vitest";
import {
  readMcpKnowledgeRequiresProject,
  withMcpKnowledgeRequiresProject,
} from "../lib/mcpKnowledgePolicy";

describe("mcpKnowledgePolicy", () => {
  it("reads requires_project from config", () => {
    expect(
      readMcpKnowledgeRequiresProject({ knowledge: { requires_project: true } }),
    ).toBe(true);
    expect(readMcpKnowledgeRequiresProject({})).toBe(false);
  });

  it("writes requires_project into config", () => {
    expect(
      withMcpKnowledgeRequiresProject({ timeout_seconds: 30 }, true),
    ).toEqual({
      timeout_seconds: 30,
      knowledge: { requires_project: true },
    });
  });
});
