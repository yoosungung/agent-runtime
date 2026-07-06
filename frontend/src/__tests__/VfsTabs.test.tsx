import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { VfsTabs } from "../components/VfsTabs";

describe("VfsTabs", () => {
  it("renders Agent, User, and Wiki tabs", () => {
    render(
      <MemoryRouter initialEntries={["/vfs/agent"]}>
        <VfsTabs />
      </MemoryRouter>,
    );
    expect(screen.getByRole("link", { name: "Agent" })).toHaveAttribute("href", "/vfs/agent");
    expect(screen.getByRole("link", { name: "User" })).toHaveAttribute("href", "/vfs/user");
    expect(screen.getByRole("link", { name: "Wiki" })).toHaveAttribute("href", "/vfs/wiki");
  });
});
