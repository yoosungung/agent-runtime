import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ChatSelectableBadge } from "../components/ChatSelectableBadge";

describe("ChatSelectableBadge", () => {
  it("shows Yes for true and defaults missing to true", () => {
    const { rerender } = render(<ChatSelectableBadge selectable />);
    expect(screen.getByText("Yes")).toHaveClass("bg-green-100");

    rerender(<ChatSelectableBadge selectable={undefined} />);
    expect(screen.getByText("Yes")).toBeInTheDocument();
  });

  it("shows No for false", () => {
    render(<ChatSelectableBadge selectable={false} />);
    expect(screen.getByText("No")).toHaveClass("bg-gray-100");
  });
});
