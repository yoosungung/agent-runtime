import { fireEvent, render, screen } from "@testing-library/react";
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

vi.mock("../hooks/useLlmPresets", () => ({
  useLlmPresets: () => ({
    data: [
      {
        id: 1,
        name: "GPT4_MINI",
        description: "Default OpenAI model",
        mode: "frontier",
        frontier_provider: "openai",
        model_id: "gpt-4o-mini",
        openai_api_base: null,
        slm_runtime: null,
        is_default: true,
        api_key_configured: true,
        context_window_tokens: 131072,
        max_output_tokens: null,
        created_at: "2026-06-22T00:00:00Z",
        updated_at: "2026-06-22T00:00:00Z",
      }
    ],
    isLoading: false,
    isError: false,
  }),
  useCreateLlmPreset: () => ({
    mutateAsync: vi.fn(),
    isPending: false,
  }),
  useUpdateLlmPreset: () => ({
    mutateAsync: vi.fn(),
    isPending: false,
  }),
  useDeleteLlmPreset: () => ({
    mutateAsync: vi.fn(),
    isPending: false,
  }),
}));

describe("InfraMetaPage", () => {
  it("renders platform infra form with tabs and handles navigation", () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={qc}>
        <InfraMetaPage />
      </QueryClientProvider>,
    );
    // General tab renders by default
    expect(screen.getByText("Platform Settings")).toBeInTheDocument();
    expect(screen.getByText("Opik URL")).toBeInTheDocument();

    // Navigate to Presets tab
    const presetsTab = screen.getByRole("button", { name: "LLM Presets" });
    fireEvent.click(presetsTab);
    expect(screen.getByText("GPT4_MINI")).toBeInTheDocument();
    expect(screen.getByText("gpt-4o-mini")).toBeInTheDocument();
    expect(screen.getByText("API Key Wired")).toBeInTheDocument();

    // Navigate to Global API Keys tab
    const keysTab = screen.getByRole("button", { name: "Global API Keys" });
    fireEvent.click(keysTab);
    expect(screen.getByText("OpenAI API Key")).toBeInTheDocument();
    expect(screen.getByText("configured")).toBeInTheDocument();
    expect(screen.getByPlaceholderText("••••••••••••••••••••• (unchanged)")).toBeInTheDocument();
  });

  it("renders tab content at full width without max-width constraint", () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const { container } = render(
      <QueryClientProvider client={qc}>
        <InfraMetaPage />
      </QueryClientProvider>,
    );

    const tabPanel = container.querySelector("[data-testid='platform-tab-panel']");
    expect(tabPanel).toBeInTheDocument();
    expect(tabPanel).toHaveClass("w-full");
    expect(tabPanel?.className).not.toMatch(/max-w-/);
  });
});
