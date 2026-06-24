import { describe, expect, it } from "vitest";
import { parseGDriveFolderId } from "../lib/gdriveConfig";

describe("parseGDriveFolderId", () => {
  it("parses /folders/ URL", () => {
    expect(
      parseGDriveFolderId(
        "https://drive.google.com/drive/folders/1UTtmbCL8OxKoCED23PlTXan6N0JYcjnu",
      ),
    ).toBe("1UTtmbCL8OxKoCED23PlTXan6N0JYcjnu");
  });

  it("returns raw id unchanged", () => {
    expect(parseGDriveFolderId("1UTtmbCL8OxKoCED23PlTXan6N0JYcjnu")).toBe(
      "1UTtmbCL8OxKoCED23PlTXan6N0JYcjnu",
    );
  });
});
