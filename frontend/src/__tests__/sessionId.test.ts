import { afterEach, describe, expect, it, vi } from "vitest";
import { generateSessionId } from "../lib/sessionId";

const UUID_RE =
  /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

describe("generateSessionId", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("uses crypto.randomUUID when available", () => {
    const randomUUID = vi.fn(() => "11111111-1111-4111-8111-111111111111");
    vi.stubGlobal("crypto", { randomUUID });

    expect(generateSessionId()).toBe("11111111-1111-4111-8111-111111111111");
    expect(randomUUID).toHaveBeenCalledOnce();
  });

  it("falls back when crypto.randomUUID is unavailable (insecure HTTP context)", () => {
    vi.stubGlobal("crypto", {});

    const id = generateSessionId();
    expect(id).toMatch(UUID_RE);
  });

  it("falls back when crypto is undefined", () => {
    vi.stubGlobal("crypto", undefined);

    const id = generateSessionId();
    expect(id).toMatch(UUID_RE);
  });
});
