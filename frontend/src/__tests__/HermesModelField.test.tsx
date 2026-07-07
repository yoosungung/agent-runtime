import { fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";
import { HermesModelField } from "../components/HermesModelField";

vi.mock("../hooks/useLlmPresets", () => ({
  useLlmPresets: () => ({
    data: [
      {
        id: 1,
        name: "CLAUDE_SONNET",
        description: null,
        mode: "frontier",
        frontier_provider: "anthropic",
        model_id: "claude-sonnet-4-6",
        openai_api_base: null,
        slm_runtime: null,
        is_default: false,
        api_key_configured: true,
        context_window_tokens: 131072,
        max_output_tokens: null,
        created_at: "2026-01-01T00:00:00Z",
        updated_at: "2026-01-01T00:00:00Z",
      },
      {
        id: 2,
        name: "SGLANG_GEMMA4",
        description: null,
        mode: "openai_compatible",
        frontier_provider: null,
        model_id: "nmilosev/gemma-4-12B-it-quantized.w4a16",
        openai_api_base: "http://sglang:30000/v1",
        slm_runtime: "sglang",
        is_default: true,
        api_key_configured: true,
        context_window_tokens: 16384,
        max_output_tokens: 8192,
        created_at: "2026-01-01T00:00:00Z",
        updated_at: "2026-01-01T00:00:00Z",
      },
    ],
    isLoading: false,
    isError: false,
  }),
}));

function renderField(props: { value?: string; onChange?: (value: string) => void }) {
  const onChange = props.onChange ?? vi.fn();
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <HermesModelField value={props.value ?? ""} onChange={onChange} />
    </QueryClientProvider>,
  );
  return onChange;
}

describe("HermesModelField", () => {
  it("renders model source selector", () => {
    renderField({});
    expect(screen.getByLabelText("LLM 모델")).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "플랫폼 기본" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "등록된 Preset" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "모델 직접 지정" })).toBeInTheDocument();
  });

  it("shows default preset summary for platform mode", () => {
    renderField({});
    expect(screen.getByText(/SGLANG_GEMMA4/)).toBeInTheDocument();
    expect(screen.getByText(/16k tokens/)).toBeInTheDocument();
  });

  it("emits preset value when preset mode selected", () => {
    const onChange = renderField({});
    fireEvent.change(screen.getByLabelText("LLM 모델"), { target: { value: "preset" } });
    expect(onChange).toHaveBeenCalledWith("preset:CLAUDE_SONNET");
  });

  it("emits explicit model value", () => {
    const onChange = renderField({});
    fireEvent.change(screen.getByLabelText("LLM 모델"), { target: { value: "explicit" } });
    expect(onChange).toHaveBeenCalledWith("anthropic:claude-sonnet-4-6");
  });

  it("parses existing preset value", () => {
    renderField({ value: "preset:CLAUDE_SONNET" });
    expect(screen.getByLabelText("Preset")).toHaveValue("CLAUDE_SONNET");
    expect(screen.queryByText("config:")).not.toBeInTheDocument();
    expect(screen.queryByText(/저장 값:/)).not.toBeInTheDocument();
  });
});
