import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { VfsBrowserPage } from "../pages/VfsBrowserPage";

vi.mock("../hooks/useVfs", () => ({
  useVfsEntries: () => ({
    data: {
      items: [
        {
          path: "/docs/",
          name: "docs",
          is_dir: true,
          size: 0,
          modified_at: "2026-01-01T00:00:00Z",
        },
        {
          path: "/readme.md",
          name: "readme.md",
          is_dir: false,
          size: 5,
          modified_at: "2026-01-01T00:00:00Z",
        },
      ],
    },
    isLoading: false,
    isError: false,
  }),
  useVfsFile: () => ({
    data: { path: "/readme.md", content: "hello", encoding: "utf-8", modified_at: null },
    isLoading: false,
  }),
  useCreateVfsFile: () => ({ mutateAsync: vi.fn(), isPending: false }),
  usePatchVfsFile: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useDeleteVfsPath: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useCreateVfsFolder: () => ({ mutateAsync: vi.fn(), isPending: false }),
  vfsErrorMessage: (err: unknown) => (err instanceof Error ? err.message : "error"),
}));

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={["/vfs/agents/agent/docs-bot"]}>
        <Routes>
          <Route path="/vfs/agents/:kind/:name" element={<VfsBrowserPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("VfsBrowserPage", () => {
  it("renders breadcrumbs and file list", () => {
    renderPage();
    expect(screen.getByRole("button", { name: "Root" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "docs/" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "readme.md" })).toBeInTheDocument();
  });

  it("opens file in editor when clicked", async () => {
    const user = userEvent.setup();
    renderPage();
    await user.click(screen.getByRole("button", { name: "readme.md" }));
    expect(screen.getByRole("textbox")).toHaveValue("hello");
  });
});
