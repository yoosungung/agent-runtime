import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";
import { InfraMetaPage } from "../pages/InfraMetaPage";

vi.mock("../hooks/useInfraMeta", () => ({
  useInfraMeta: () => ({
    data: {
      scope: "global",
      scope_key: "",
      env: { OPIK_URL: "http://opik/api" },
      secret_keys: ["OPENAI_API_KEY"],
      updated_at: null,
    },
    isLoading: false,
    isError: false,
  }),
  useUpsertInfraMeta: () => ({
    mutateAsync: vi.fn(),
    isPending: false,
  }),
}));

describe("InfraMetaPage", () => {
  it("renders platform infra form", () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={qc}>
        <InfraMetaPage />
      </QueryClientProvider>,
    );
    expect(screen.getByText("Platform Infra")).toBeInTheDocument();
    expect(screen.getByText("Opik URL")).toBeInTheDocument();
    expect(screen.getByText("(configured)")).toBeInTheDocument();
  });
});
