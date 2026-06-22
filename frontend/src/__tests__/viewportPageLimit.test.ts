import { describe, expect, it } from "vitest";
import { computeViewportPageLimit } from "../lib/viewportPageLimit";

describe("computeViewportPageLimit", () => {
  it("returns min when available space is too small", () => {
    expect(computeViewportPageLimit(400, 380, { min: 10 })).toBe(10);
  });

  it("fits rows from remaining viewport height below anchor", () => {
    // 900px viewport, list starts at 300px, ~116px chrome → 484px for rows → 11 rows
    expect(
      computeViewportPageLimit(900, 300, {
        min: 10,
        max: 50,
        rowHeight: 44,
        chromeHeight: 100,
        bottomMargin: 16,
      }),
    ).toBe(11);
  });

  it("never goes below min", () => {
    expect(
      computeViewportPageLimit(700, 600, {
        min: 10,
        rowHeight: 44,
        chromeHeight: 80,
      }),
    ).toBe(10);
  });

  it("caps at max", () => {
    expect(
      computeViewportPageLimit(3000, 100, {
        min: 10,
        max: 50,
        rowHeight: 44,
        chromeHeight: 80,
      }),
    ).toBe(50);
  });
});
