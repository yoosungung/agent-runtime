import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { FormPageLayout } from "../components/FormPageLayout";

describe("FormPageLayout", () => {
  it("renders full-width card layout", () => {
    const { container } = render(
      <FormPageLayout title="New Agent" description="Helper text">
        <p>Form body</p>
      </FormPageLayout>,
    );
    expect(screen.getByRole("heading", { name: "New Agent" })).toBeInTheDocument();
    expect(screen.getByText("Helper text")).toBeInTheDocument();
    expect(screen.getByText("Form body")).toBeInTheDocument();
    expect(container.firstChild).toHaveClass("w-full");
  });
});
