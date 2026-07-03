import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { GeneralAgentKnowledgeProjectsField } from "../components/GeneralAgentKnowledgeProjectsField";

vi.mock("../hooks/useKnowledgeProjects", () => ({
  useKnowledgeProjects: () => ({
    data: {
      items: [
        {
          tenant: "acme",
          id: "p1",
          slug: "docs",
          name: "Docs",
          created_at: "2026-01-01T00:00:00Z",
        },
      ],
    },
    isLoading: false,
    isError: false,
  }),
  useKnowledgeProjectBinding: () => ({
    data: {
      tenant: "acme",
      project_id: "p1",
      project_slug: "docs",
      rag: { index_namespace: "path_graph_dev_col-1", filter: {} },
      graph: { nebula_space: "space-1" },
      wiki: { vfs_mount: "/wiki/docs/" },
    },
  }),
}));

describe("GeneralAgentKnowledgeProjectsField", () => {
  it("renders projects and toggles selection", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(
      <GeneralAgentKnowledgeProjectsField selectedIds={[]} onChange={onChange} />,
    );
    expect(screen.getByText("Docs")).toBeInTheDocument();
    await user.click(screen.getByRole("checkbox"));
    expect(onChange).toHaveBeenCalledWith(["p1"]);
  });

  it("shows binding preview when selected", () => {
    render(
      <GeneralAgentKnowledgeProjectsField
        selectedIds={["p1"]}
        onChange={() => {}}
      />,
    );
    expect(screen.getByText(/col-1/)).toBeInTheDocument();
    expect(screen.getByText(/space-1/)).toBeInTheDocument();
  });
});
