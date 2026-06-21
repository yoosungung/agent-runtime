import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";
import { BucketPage } from "../pages/BucketPage";

const hex64 = "a".repeat(64);

vi.mock("../hooks/useBucket", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../hooks/useBucket")>();
  return {
    ...actual,
    useBucketInfo: () => ({
      data: { backend: "local", root_label: "/var/lib/admin/bundles" },
    }),
    useBucketObjects: () => ({
      data: {
        items: [
          {
            key: `${hex64}.zip`,
            name: `${hex64}.zip`,
            kind: "file",
            size: 1024,
            last_modified: "2026-01-01T00:00:00Z",
            ref_count: 1,
            in_use: true,
          },
          {
            key: "notes.txt",
            name: "notes.txt",
            kind: "file",
            size: 12,
            last_modified: "2026-01-01T00:00:00Z",
            ref_count: 0,
            in_use: false,
          },
          {
            key: "imports/",
            name: "imports",
            kind: "folder",
            size: null,
            last_modified: "2026-01-01T00:00:00Z",
            ref_count: 0,
            in_use: false,
          },
        ],
      },
      isLoading: false,
      isError: false,
    }),
    useCreateBucketFolder: () => ({ mutateAsync: vi.fn(), isPending: false }),
    useUploadBucketObject: () => ({ mutateAsync: vi.fn(), isPending: false }),
    useDeleteBucketObjects: () => ({ mutateAsync: vi.fn(), isPending: false }),
    useMoveBucketObjects: () => ({ mutateAsync: vi.fn(), isPending: false }),
    useBucketDownloadUrl: () => ({ mutateAsync: vi.fn(), isPending: false }),
  };
});

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <BucketPage />
    </QueryClientProvider>,
  );
}

describe("BucketPage", () => {
  it("renders backend badge and in-use row disabled", () => {
    renderPage();
    expect(screen.getByText(/Local:/)).toBeInTheDocument();
    expect(screen.getAllByText("In use").length).toBeGreaterThan(0);
    const inUseCheckbox = screen.getByLabelText(`Select ${hex64}.zip`);
    expect(inUseCheckbox).toBeDisabled();
  });

  it("navigates folders via breadcrumb and folder link", async () => {
    const user = userEvent.setup();
    renderPage();
    await user.click(screen.getByRole("button", { name: "imports/" }));
    expect(screen.getByRole("button", { name: "imports" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Root" }));
    expect(screen.getByRole("button", { name: "Root" })).toHaveClass("font-semibold");
  });
});
