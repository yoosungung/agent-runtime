import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { WorkflowStatusBadge } from "../components/WorkflowStatusBadge";

describe("WorkflowStatusBadge", () => {
  it("renders Argo Succeeded with success styling", () => {
    render(<WorkflowStatusBadge status="Succeeded" />);
    const badge = screen.getByText("Succeeded");
    expect(badge.className).toContain("bg-green-100");
  });

  it("renders PG submitted with neutral styling", () => {
    render(<WorkflowStatusBadge status="submitted" />);
    const badge = screen.getByText("submitted");
    expect(badge.className).toContain("bg-slate-100");
  });

  it("renders Failed with error styling", () => {
    render(<WorkflowStatusBadge status="Failed" />);
    const badge = screen.getByText("Failed");
    expect(badge.className).toContain("bg-red-100");
  });
});
