import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { GeneralAgentVisibilityField } from "../components/GeneralAgentVisibilityField";

vi.mock("../hooks/useSession", () => ({
  useSession: vi.fn(),
}));

import { useSession } from "../hooks/useSession";

describe("GeneralAgentVisibilityField", () => {
  it("renders visibility as a select with three options", () => {
    vi.mocked(useSession).mockReturnValue({
      data: { tenant: "acme" },
    } as ReturnType<typeof useSession>);

    render(<GeneralAgentVisibilityField value="private" onChange={vi.fn()} />);

    const select = screen.getByLabelText("사용 권한");
    expect(select.tagName).toBe("SELECT");

    const options = Array.from(select.querySelectorAll("option")).map(
      (o) => o.textContent,
    );
    expect(options).toEqual(["나만 사용", "내 테넌트만 사용", "모두 사용"]);
  });

  it("disables tenant option when session has no tenant", () => {
    vi.mocked(useSession).mockReturnValue({
      data: { tenant: null },
    } as ReturnType<typeof useSession>);

    render(<GeneralAgentVisibilityField value="private" onChange={vi.fn()} />);

    const tenantOption = screen.getByRole("option", { name: "내 테넌트만 사용" });
    expect(tenantOption).toBeDisabled();
    expect(
      screen.getByText(/tenant가 없어.*내 테넌트만 사용.*선택할 수 없습니다/),
    ).toBeInTheDocument();
  });

  it("calls onChange when a different option is selected", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    vi.mocked(useSession).mockReturnValue({
      data: { tenant: "acme" },
    } as ReturnType<typeof useSession>);

    render(<GeneralAgentVisibilityField value="private" onChange={onChange} />);

    await user.selectOptions(screen.getByLabelText("사용 권한"), "public");
    expect(onChange).toHaveBeenCalledWith("public");
  });
});
