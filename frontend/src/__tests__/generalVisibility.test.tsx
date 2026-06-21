import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import {
  GENERAL_VISIBILITY_OPTIONS,
  generalVisibilityLabel,
} from "../lib/generalVisibility";

describe("generalVisibility", () => {
  it("exposes three Korean labels", () => {
    expect(GENERAL_VISIBILITY_OPTIONS).toHaveLength(3);
    expect(screen.queryByText("나만 사용")).not.toBeInTheDocument();
    expect(generalVisibilityLabel("private")).toBe("나만 사용");
    expect(generalVisibilityLabel("tenant")).toBe("내 테넌트만 사용");
    expect(generalVisibilityLabel("public")).toBe("모두 사용");
  });
});
