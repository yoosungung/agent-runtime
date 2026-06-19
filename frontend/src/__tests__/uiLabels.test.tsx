import { describe, expect, it } from "vitest";
import {
  createSubmitLabel,
  listNewButtonLabel,
  listNewImageButtonLabel,
  newPageTitle,
  uploadSubmitLabel,
} from "../lib/uiLabels";

describe("uiLabels", () => {
  it("uses consistent list new button labels", () => {
    expect(listNewButtonLabel("agent")).toBe("+ New Agent");
    expect(listNewButtonLabel("mcp")).toBe("+ New MCP");
    expect(listNewImageButtonLabel("agent")).toBe("+ New Agent Image");
    expect(listNewImageButtonLabel("mcp")).toBe("+ New MCP Image");
  });

  it("uses clear page titles per tier", () => {
    expect(newPageTitle("agent", "agent")).toBe("New Agent");
    expect(newPageTitle("bundle", "agent")).toBe("New Bundle Agent");
    expect(newPageTitle("bundle", "mcp")).toBe("New Bundle MCP");
    expect(newPageTitle("container", "mcp")).toBe("New MCP Image");
  });

  it("uses matching submit labels", () => {
    expect(createSubmitLabel("agent")).toBe("Create Agent");
    expect(uploadSubmitLabel("mcp")).toBe("Upload MCP");
  });
});
