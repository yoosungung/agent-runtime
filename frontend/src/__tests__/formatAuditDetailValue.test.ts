import { describe, expect, it } from "vitest";
import { formatAuditDetailValue } from "../lib/formatAuditDetailValue";

describe("formatAuditDetailValue", () => {
  it("formats scalars", () => {
    expect(formatAuditDetailValue("dev")).toBe("dev");
    expect(formatAuditDetailValue(3)).toBe("3");
    expect(formatAuditDetailValue(true)).toBe("true");
    expect(formatAuditDetailValue(null)).toBe("—");
    expect(formatAuditDetailValue(undefined)).toBe("—");
  });

  it("joins string arrays for changed_fields style values", () => {
    expect(formatAuditDetailValue(["system_prompt", "mcp_servers"])).toBe(
      "system_prompt, mcp_servers",
    );
    expect(formatAuditDetailValue([])).toBe("—");
  });

  it("stringifies objects instead of [object Object]", () => {
    expect(formatAuditDetailValue({ status: "ok", purged_count: 2 })).toBe(
      '{"status":"ok","purged_count":2}',
    );
  });

  it("summarizes upload item arrays", () => {
    expect(
      formatAuditDetailValue([
        { filename: "a.pdf", status: "uploaded" },
        { filename: "b.pdf", status: "skipped", reason: "duplicate" },
      ]),
    ).toBe("a.pdf: uploaded; b.pdf: skipped (duplicate)");
  });
});
