import { afterEach, describe, expect, it, vi } from "vitest";
import { copyToClipboard } from "../lib/copyToClipboard";

describe("copyToClipboard", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("uses navigator.clipboard when writeText succeeds", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    vi.stubGlobal("navigator", { clipboard: { writeText } });

    const ok = await copyToClipboard("ak_1_secret");

    expect(ok).toBe(true);
    expect(writeText).toHaveBeenCalledWith("ak_1_secret");
  });

  it("falls back to execCommand when clipboard API fails", async () => {
    const writeText = vi.fn().mockRejectedValue(new Error("denied"));
    const execCommand = vi.fn().mockReturnValue(true);
    vi.stubGlobal("navigator", { clipboard: { writeText } });
    document.execCommand = execCommand as typeof document.execCommand;

    const ok = await copyToClipboard("ak_2_token");

    expect(ok).toBe(true);
    expect(execCommand).toHaveBeenCalledWith("copy");
  });

  it("returns false when both methods fail", async () => {
    vi.stubGlobal("navigator", {});
    document.execCommand = vi.fn().mockReturnValue(false) as typeof document.execCommand;

    const ok = await copyToClipboard("ak_3_fail");

    expect(ok).toBe(false);
  });
});
