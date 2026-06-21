import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { KindTabs } from "../components/KindTabs";

describe("KindTabs", () => {
  it("renders Agent and MCP tabs for bundle section", () => {
    render(
      <MemoryRouter initialEntries={["/bundle/agents"]}>
        <KindTabs basePath="/bundle" />
      </MemoryRouter>,
    );
    expect(screen.getByRole("link", { name: "Agent" })).toHaveAttribute(
      "href",
      "/bundle/agents",
    );
    expect(screen.getByRole("link", { name: "MCP" })).toHaveAttribute(
      "href",
      "/bundle/mcp",
    );
    expect(screen.queryByRole("link", { name: "Bucket" })).not.toBeInTheDocument();
  });

  it("shows Bucket tab for bundle section when showBucket is true", () => {
    render(
      <MemoryRouter initialEntries={["/bundle/bucket"]}>
        <KindTabs basePath="/bundle" showBucket />
      </MemoryRouter>,
    );
    expect(screen.getByRole("link", { name: "Bucket" })).toHaveAttribute(
      "href",
      "/bundle/bucket",
    );
  });

  it("does not show Bucket tab on container section", () => {
    render(
      <MemoryRouter initialEntries={["/container/agents"]}>
        <KindTabs basePath="/container" showBucket />
      </MemoryRouter>,
    );
    expect(screen.queryByRole("link", { name: "Bucket" })).not.toBeInTheDocument();
  });
});
