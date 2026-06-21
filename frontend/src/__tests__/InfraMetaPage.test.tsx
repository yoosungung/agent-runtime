import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";
import { InfraMetaPage } from "../pages/InfraMetaPage";

vi.mock("../hooks/useInfraMeta", () => ({
  INFRA_UI_ENV_KEYS: {
    opikUrl: "OPIK_URL",
    opikWorkspace: "OPIK_WORKSPACE",
    defaultLlmModel: "DEFAULT_LLM_MODEL",
    openaiApiBase: "OPENAI_API_BASE",
    llmRuntime: "LLM_RUNTIME",
    otlpEndpoint: "OTLP_ENDPOINT",
  },
  INFRA_UI_SECRET_KEYS: [
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "GOOGLE_API_KEY",
    "OPIK_API_KEY",
  ],
  useInfraMeta: () => ({
    data: {
      scope: "global",
      scope_key: "",
      env: {
        OPIK_URL: "http://opik/api",
        DEFAULT_LLM_MODEL: "openai:gpt-4o-mini",
      },
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
  it("renders platform infra form with LLM provider options", () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={qc}>
        <InfraMetaPage />
      </QueryClientProvider>,
    );
    expect(screen.getByText("Platform")).toBeInTheDocument();
    expect(screen.getByText("Opik URL")).toBeInTheDocument();
    expect(screen.getByText("(configured)")).toBeInTheDocument();
    expect(screen.getByText("Frontier (cloud API)")).toBeInTheDocument();
    expect(screen.getByText(/Self-hosted \(vLLM \/ SGLang\)/)).toBeInTheDocument();
    expect(screen.getByDisplayValue("gpt-4o-mini")).toBeInTheDocument();
  });
});
