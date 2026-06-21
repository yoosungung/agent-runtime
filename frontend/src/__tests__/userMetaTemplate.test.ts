import { describe, expect, it } from "vitest";
import {
  getNestedValue,
  setNestedValue,
  hasTemplateFields,
  isUserMetaRequired,
  serializeUserMetaTemplateForSave,
} from "../lib/userMetaTemplate";

describe("userMetaTemplate helpers", () => {
  it("reads and writes nested paths", () => {
    const config = setNestedValue({}, "outlook.mailbox", "user@example.com");
    expect(getNestedValue(config, "outlook.mailbox")).toBe("user@example.com");
  });

  it("detects template fields", () => {
    expect(hasTemplateFields({ fields: [{ path: "a", label: "A" }] })).toBe(true);
    expect(hasTemplateFields({})).toBe(false);
    expect(hasTemplateFields({ enabled: false, fields: [{ path: "a", label: "A" }] })).toBe(
      false,
    );
  });

  it("treats enabled=false as not required", () => {
    expect(isUserMetaRequired({ enabled: false })).toBe(false);
    expect(isUserMetaRequired({})).toBe(false);
    expect(isUserMetaRequired({ fields: [{ path: "a", label: "A" }] })).toBe(true);
  });

  it("serializes unchecked template minimally", () => {
    expect(
      serializeUserMetaTemplateForSave({
        enabled: false,
        description: "",
        fields: [{ path: "stale", label: "Stale" }],
        secrets_ref_enabled: true,
      }),
    ).toEqual({ enabled: false });
  });
});
