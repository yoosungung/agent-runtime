import { describe, expect, it } from "vitest";

import {
  fileMatchesAccept,
  filterAcceptedFiles,
  parseAcceptExtensions,
} from "../lib/fileDropHelpers";

describe("fileDropHelpers", () => {
  it("parses accept extensions with optional spaces", () => {
    expect(parseAcceptExtensions(".pdf,.hwp,.docx")).toEqual([
      ".pdf",
      ".hwp",
      ".docx",
    ]);
    expect(parseAcceptExtensions(".pdf, .hwp")).toEqual([".pdf", ".hwp"]);
  });

  it("matches extensions case-insensitively", () => {
    expect(fileMatchesAccept("Report.PDF", ".pdf,.hwp")).toBe(true);
    expect(fileMatchesAccept("notes.txt", ".pdf,.hwp")).toBe(false);
  });

  it("filters batch keeping only accepted files", () => {
    const files = [
      new File(["a"], "a.pdf", { type: "application/pdf" }),
      new File(["b"], "b.exe", { type: "application/octet-stream" }),
      new File(["c"], "c.HWP", { type: "application/octet-stream" }),
    ];
    const { accepted, rejected } = filterAcceptedFiles(files, ".pdf,.hwp", 100);
    expect(accepted.map((f) => f.name)).toEqual(["a.pdf", "c.HWP"]);
    expect(rejected).toHaveLength(1);
    expect(rejected[0].displayName).toBe("b.exe");
    expect(rejected[0].reason).toContain("extension");
  });
});
