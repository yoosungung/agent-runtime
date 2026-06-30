import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { GeneralAgentChatSelectableField } from "../components/GeneralAgentChatSelectableField";

describe("GeneralAgentChatSelectableField", () => {
  it("renders chat selectable checkbox", () => {
    render(
      <GeneralAgentChatSelectableField checked onChange={() => undefined} />,
    );
    expect(screen.getByRole("checkbox")).toBeChecked();
    expect(screen.getByText(/Chat에서 선택 가능/)).toBeInTheDocument();
  });
});
