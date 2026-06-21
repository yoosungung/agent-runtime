/** Envoy agent invoke URL (Ingress `/v1/agents/`). Override at build or in `.env.local`. */
export function getAgentsInvokeUrl(): string {
  const configured = import.meta.env.VITE_AGENTS_INVOKE_URL?.trim();
  if (configured) {
    return configured;
  }
  return "/v1/agents/invoke";
}
