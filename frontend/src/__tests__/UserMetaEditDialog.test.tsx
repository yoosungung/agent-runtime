import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi, beforeEach } from "vitest";
import { UserMetaEditDialog } from "../components/UserMetaEditDialog";

const mockUseMyUserMeta = vi.fn();
const mockUseUpsertMyUserMeta = vi.fn();

vi.mock("../hooks/useMyUserMeta", () => ({
  useMyUserMeta: (...args: unknown[]) => mockUseMyUserMeta(...args),
  useUpsertMyUserMeta: () => mockUseUpsertMyUserMeta(),
}));

describe("UserMetaEditDialog", () => {
  beforeEach(() => {
    mockUseMyUserMeta.mockReturnValue({
      data: {
        kind: "mcp",
        name: "utility-server",
        version: "1.0.0",
        user_meta_template: {
          description: "Utility settings",
          fields: [{ path: "token", label: "Token", required: true }],
        },
        config: {},
        secrets_ref: null,
      },
      isLoading: false,
      isError: false,
    });
    mockUseUpsertMyUserMeta.mockReturnValue({
      mutateAsync: vi.fn(),
      isPending: false,
    });
  });

  it("renders nothing when closed", () => {
    const { container } = render(
      <UserMetaEditDialog
        open={false}
        kind="mcp"
        name="utility-server"
        onClose={vi.fn()}
      />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("shows resource name and form when open", () => {
    render(
      <UserMetaEditDialog
        open
        kind="mcp"
        name="utility-server"
        onClose={vi.fn()}
      />,
    );

    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByText("utility-server")).toBeInTheDocument();
    expect(screen.getByText("Utility settings")).toBeInTheDocument();
  });

  it("calls onClose when cancel is clicked", async () => {
    const onClose = vi.fn();
    const user = userEvent.setup();

    render(
      <UserMetaEditDialog
        open
        kind="mcp"
        name="utility-server"
        onClose={onClose}
      />,
    );

    await user.click(screen.getByRole("button", { name: /cancel/i }));
    expect(onClose).toHaveBeenCalledOnce();
  });
});
