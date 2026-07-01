import { describe, expect, it } from "vitest";
import { parseSkillsInput, readHermesConfig } from "../lib/hermesAgent";

describe("hermesAgent", () => {
  it("readHermesConfig extracts hermes section", () => {
    expect(
      readHermesConfig({
        hermes: {
          soul: "You are helpful.",
          mcp_servers: ["search-server"],
          skills: ["plan"],
          model: "openai/gpt-4o",
        },
      }),
    ).toEqual({
      soul: "You are helpful.",
      mcp_servers: ["search-server"],
      skills: ["plan"],
      model: "openai/gpt-4o",
    });
  });

  it("parseSkillsInput splits comma-separated names", () => {
    expect(parseSkillsInput("plan, search ,")).toEqual(["plan", "search"]);
  });
});
