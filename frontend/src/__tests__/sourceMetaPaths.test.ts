import { describe, expect, it } from "vitest";
import { sourceMetaDetailPath, sourceMetaListPath } from "../lib/sourceMetaPaths";

describe("sourceMetaDetailPath", () => {
  it("routes general agents to /agents/:id", () => {
    expect(
      sourceMetaDetailPath({ id: 1, kind: "agent", deploy_mode: "general" }),
    ).toBe("/agents/1");
  });

  it("routes bundle agents to /bundle/agents/:id", () => {
    expect(
      sourceMetaDetailPath({ id: 4, kind: "agent", deploy_mode: "bundle" }),
    ).toBe("/bundle/agents/4");
  });

  it("routes bundle mcp to /mcp-servers/:id", () => {
    expect(
      sourceMetaDetailPath({ id: 2, kind: "mcp", deploy_mode: "bundle" }),
    ).toBe("/mcp-servers/2");
  });
});

describe("sourceMetaListPath", () => {
  it("routes bundle agents back to /bundle/agents", () => {
    expect(
      sourceMetaListPath({ kind: "agent", deploy_mode: "bundle" }),
    ).toBe("/bundle/agents");
  });
});
