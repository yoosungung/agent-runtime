import { describe, expect, it } from "vitest";
import { roleAtLeast } from "../lib/roles";

describe("roles", () => {
  it("orders user < developer < admin", () => {
    expect(roleAtLeast("user", "user")).toBe(true);
    expect(roleAtLeast("user", "developer")).toBe(false);
    expect(roleAtLeast("developer", "user")).toBe(true);
    expect(roleAtLeast("admin", "developer")).toBe(true);
    expect(roleAtLeast("developer", "admin")).toBe(false);
  });
});
