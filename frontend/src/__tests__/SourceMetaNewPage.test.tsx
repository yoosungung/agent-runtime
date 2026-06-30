import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";
import { SourceMetaNewPage } from "../pages/SourceMetaNewPage";

vi.mock("../hooks/useSourceMeta", () => ({
  useCreateSourceMeta: () => ({
    mutateAsync: vi.fn(),
    isPending: false,
  }),
  useUploadBundle: () => ({
    mutateAsync: vi.fn(),
    isPending: false,
  }),
}));

function renderPage(kind: "agent" | "mcp" = "agent") {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <SourceMetaNewPage kind={kind} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("SourceMetaNewPage", () => {
  it("keeps shared fields when switching between External URI and ZIP Upload", async () => {
    const user = userEvent.setup();
    renderPage("agent");

    await user.type(screen.getByLabelText(/^Name/), "my-agent");
    await user.type(screen.getByLabelText(/^Version/), "1.0.0");
    await user.selectOptions(screen.getByLabelText(/^Runtime Pool/), "agent:compiled_graph");
    await user.type(screen.getByLabelText(/^Entrypoint/), "module.path:factory");

    await user.click(screen.getByRole("button", { name: "ZIP Upload" }));

    expect(screen.getByLabelText(/^Name/)).toHaveValue("my-agent");
    expect(screen.getByLabelText(/^Version/)).toHaveValue("1.0.0");
    expect(screen.getByLabelText(/^Runtime Pool/)).toHaveValue("agent:compiled_graph");
    expect(screen.getByLabelText(/^Entrypoint/)).toHaveValue("module.path:factory");

    await user.click(screen.getByRole("button", { name: "External URI" }));

    expect(screen.getByLabelText(/^Name/)).toHaveValue("my-agent");
    expect(screen.getByLabelText(/^Version/)).toHaveValue("1.0.0");
    expect(screen.getByLabelText(/^Runtime Pool/)).toHaveValue("agent:compiled_graph");
    expect(screen.getByLabelText(/^Entrypoint/)).toHaveValue("module.path:factory");
  });

  it("shows chat selectable for bundle agent", () => {
    renderPage("agent");
    expect(screen.getByText(/Chat에서 선택 가능/)).toBeInTheDocument();
  });

  it("hides chat selectable for bundle MCP", () => {
    renderPage("mcp");
    expect(screen.queryByText(/Chat에서 선택 가능/)).not.toBeInTheDocument();
  });

  it("lists bundle MCP runtime pools without image-mode custom", () => {
    renderPage("mcp");

    const select = screen.getByLabelText(/^Runtime Pool/);
    const options = Array.from(select.querySelectorAll("option"))
      .map((option) => option.textContent)
      .filter(Boolean);

    expect(options).toContain("mcp:fastmcp");
    expect(options).toContain("mcp:mcp_sdk");
    expect(options).not.toContain("mcp:custom");
  });
});
