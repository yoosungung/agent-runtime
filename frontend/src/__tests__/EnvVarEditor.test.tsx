import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { EnvVarEditor } from "../components/EnvVarEditor";

describe("EnvVarEditor", () => {
  it("adds a new empty row when + Add variable is clicked", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();

    render(<EnvVarEditor value={{}} onChange={onChange} />);

    expect(screen.getAllByPlaceholderText("LOG_LEVEL")).toHaveLength(1);

    await user.click(screen.getByRole("button", { name: "+ Add variable" }));

    expect(screen.getAllByPlaceholderText("LOG_LEVEL")).toHaveLength(2);
  });

  it("keeps an added row while the new key is still empty", async () => {
    const user = userEvent.setup();
    let env: Record<string, string> = {};
    const onChange = vi.fn((next: Record<string, string>) => {
      env = next;
    });

    const { rerender } = render(<EnvVarEditor value={env} onChange={onChange} />);

    await user.click(screen.getByRole("button", { name: "+ Add variable" }));
    rerender(<EnvVarEditor value={env} onChange={onChange} />);

    expect(screen.getAllByPlaceholderText("LOG_LEVEL")).toHaveLength(2);
  });

  it("emits env entries when key and value are filled", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();

    render(<EnvVarEditor value={{}} onChange={onChange} />);

    await user.type(screen.getByPlaceholderText("LOG_LEVEL"), "LOG_LEVEL");
    await user.type(screen.getByPlaceholderText("debug"), "info");

    expect(onChange).toHaveBeenLastCalledWith({ LOG_LEVEL: "info" });
  });
});
