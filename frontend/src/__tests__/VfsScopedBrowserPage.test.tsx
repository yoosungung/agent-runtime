import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { VfsScopedBrowserPage } from "../pages/VfsScopedBrowserPage";

vi.mock("../hooks/useVfs", () => ({
  useVfsUserEntries: () => ({
    data: {
      items: [
        {
          path: "/notes.md",
          name: "notes.md",
          is_dir: false,
          size: 5,
          modified_at: "2026-01-01T00:00:00Z",
        },
      ],
    },
    isLoading: false,
    isError: false,
  }),
  useVfsUserFile: () => ({
    data: { path: "/notes.md", content: "personal", encoding: "utf-8", modified_at: null },
    isLoading: false,
  }),
  useCreateVfsUserFile: () => ({ mutateAsync: vi.fn(), isPending: false }),
  usePatchVfsUserFile: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useDeleteVfsUserPath: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useCreateVfsUserFolder: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useVfsWikiEntries: () => ({ data: { items: [] }, isLoading: false, isError: false }),
  useVfsWikiFile: () => ({ data: undefined, isLoading: false }),
  useCreateVfsWikiFile: () => ({ mutateAsync: vi.fn(), isPending: false }),
  usePatchVfsWikiFile: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useDeleteVfsWikiPath: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useCreateVfsWikiFolder: () => ({ mutateAsync: vi.fn(), isPending: false }),
  vfsErrorMessage: (err: unknown) => (err instanceof Error ? err.message : "error"),
}));

vi.mock("../pipeline/hooks/usePipeline", () => ({
  usePipelineProject: () => ({ data: undefined }),
}));

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter
        initialEntries={[{ pathname: "/vfs/user/10", state: { username: "alice" } }]}
      >
        <Routes>
          <Route path="/vfs/user/:id" element={<VfsScopedBrowserPage scope="user" />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("VfsScopedBrowserPage", () => {
  it("renders agent-style browser for user scope", () => {
    renderPage();
    expect(screen.getByRole("button", { name: "User" })).toBeInTheDocument();
    expect(screen.getByText("alice")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "New Folder" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "notes.md" })).toBeInTheDocument();
  });

  it("opens file in editor when clicked", async () => {
    const user = userEvent.setup();
    renderPage();
    await user.click(screen.getByRole("button", { name: "notes.md" }));
    expect(screen.getByRole("textbox")).toHaveValue("personal");
  });
});
