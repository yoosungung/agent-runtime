import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it } from "vitest";
import { IngestStateBadge } from "../../knowledge/components/IngestStateBadge";

describe("IngestStateBadge", () => {
  it("renders ingest state label", () => {
    render(<IngestStateBadge state="pending" />);
    expect(screen.getByText("pending")).toBeInTheDocument();
  });
});

describe("FilesProjectsPage", () => {
  it("smoke import", async () => {
    const { FilesProjectsPage } = await import("../pages/FilesProjectsPage");
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={qc}>
        <MemoryRouter>
          <FilesProjectsPage />
        </MemoryRouter>
      </QueryClientProvider>,
    );
    expect(screen.getByText("파일관리")).toBeInTheDocument();
  });
});
