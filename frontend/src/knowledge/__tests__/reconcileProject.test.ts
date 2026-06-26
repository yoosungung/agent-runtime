import { describe, expect, it } from "vitest";
import { pickFallbackProjectId } from "../reconcileProject";

const PROJECTS = [
  { id: "51bf7260-02fa-4b1a-88d9-6ca32accf00a" },
  { id: "0d64f69c-2777-421f-89b0-d938cf50b74e" },
];

describe("pickFallbackProjectId", () => {
  it("keeps a project id that exists in the list", () => {
    expect(
      pickFallbackProjectId("0d64f69c-2777-421f-89b0-d938cf50b74e", PROJECTS),
    ).toBe("0d64f69c-2777-421f-89b0-d938cf50b74e");
  });

  it("falls back to the first project when the id is stale", () => {
    expect(
      pickFallbackProjectId("ccf13679-5c67-4297-b5a8-4b21a9937e8a", PROJECTS),
    ).toBe("51bf7260-02fa-4b1a-88d9-6ca32accf00a");
  });

  it("returns null when there are no projects", () => {
    expect(pickFallbackProjectId("any", [])).toBeNull();
  });
});
