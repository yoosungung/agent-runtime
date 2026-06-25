import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";
import { KnowledgeProjectProvider } from "../../knowledge/context/KnowledgeProjectContext";
import { PipelineSidebar } from "../components/PipelineSidebar";

vi.mock("../hooks/usePipeline", () => ({
  usePipelineProjects: vi.fn(() => ({
    data: {
      items: [
        { id: "p1", name: "Alpha Docs", slug: "alpha" },
        { id: "p2", name: "Beta Wiki", slug: "beta" },
      ],
    },
    isLoading: false,
    isError: false,
  })),
  useCreatePipelineProject: vi.fn(() => ({
    mutateAsync: vi.fn(),
    isPending: false,
  })),
}));

function renderSidebar(activeProjectId = "") {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <KnowledgeProjectProvider>
        <MemoryRouter>
          <PipelineSidebar activeProjectId={activeProjectId} />
        </MemoryRouter>
      </KnowledgeProjectProvider>
    </QueryClientProvider>,
  );
}

describe("PipelineSidebar", () => {
  it("shows search, credentials, and filterable project list", async () => {
    const user = userEvent.setup();
    renderSidebar();

    expect(screen.getByLabelText(/search/i)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /credentials/i })).toHaveAttribute(
      "href",
      "/pipeline/credentials",
    );
    expect(screen.getByText("Alpha Docs")).toBeInTheDocument();
    expect(screen.getByText("Beta Wiki")).toBeInTheDocument();

    await user.type(screen.getByLabelText(/search/i), "beta");
    expect(screen.queryByText("Alpha Docs")).not.toBeInTheDocument();
    expect(screen.getByText("Beta Wiki")).toBeInTheDocument();
  });

  it("opens new project dialog from sidebar button", async () => {
    const user = userEvent.setup();
    renderSidebar();

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /\+ New Project/i }));
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByLabelText(/^Name$/i)).toBeInTheDocument();
  });
});
