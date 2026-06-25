import { useMemo, useState } from "react";
import { Link, NavLink } from "react-router-dom";
import { usePipelineProjects } from "../hooks/usePipeline";
import { useKnowledgeProjectContext } from "../../knowledge/context/KnowledgeProjectContext";
import { PipelineNewProjectDialog } from "./PipelineNewProjectDialog";

const linkClass = ({ isActive }: { isActive: boolean }) =>
  `block rounded px-3 py-2 text-sm ${
    isActive
      ? "bg-blue-50 text-blue-700 font-medium"
      : "text-gray-700 hover:bg-gray-50"
  }`;

const projectLinkClass = (active: boolean) =>
  `block rounded px-3 py-2 text-sm truncate ${
    active
      ? "bg-blue-50 text-blue-700 font-medium"
      : "text-gray-700 hover:bg-gray-50"
  }`;

type Props = {
  activeProjectId?: string;
};

export function PipelineSidebar({ activeProjectId = "" }: Props) {
  const [search, setSearch] = useState("");
  const [newProjectOpen, setNewProjectOpen] = useState(false);
  const { setSelectedProjectId } = useKnowledgeProjectContext();
  const { data, isLoading, isError } = usePipelineProjects();
  const projects = data?.items ?? [];

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return projects;
    return projects.filter(
      (p) =>
        p.name.toLowerCase().includes(q) || p.slug.toLowerCase().includes(q),
    );
  }, [projects, search]);

  function onSelectProject(projectId: string) {
    setSelectedProjectId(projectId);
  }

  return (
    <aside className="w-full lg:w-56 shrink-0">
      <h2 className="text-lg font-semibold text-gray-900 mb-3">Pipeline</h2>

      <div className="mb-4 space-y-2">
        <label htmlFor="pipeline-search" className="sr-only">
          Search projects
        </label>
        <input
          id="pipeline-search"
          type="search"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search projects…"
          className="w-full border border-gray-300 rounded px-2 py-1.5 text-sm"
        />
        <button
          type="button"
          onClick={() => setNewProjectOpen(true)}
          className="w-full text-sm bg-blue-600 hover:bg-blue-700 text-white rounded px-2 py-1.5 font-medium"
        >
          + New Project
        </button>
      </div>

      <PipelineNewProjectDialog
        open={newProjectOpen}
        onClose={() => setNewProjectOpen(false)}
      />

      <nav className="mb-4">
        <NavLink to="/pipeline/credentials" className={linkClass}>
          Credentials
        </NavLink>
      </nav>

      <div className="border-t border-gray-200 pt-4">
        <h3 className="text-xs font-medium text-gray-500 uppercase tracking-wide mb-2">
          Projects
        </h3>
        {isLoading && <p className="text-sm text-gray-500">Loading…</p>}
        {isError && (
          <p className="text-sm text-red-600">Failed to load projects.</p>
        )}
        <ul className="space-y-0.5 max-h-[50vh] overflow-y-auto">
          {filtered.length === 0 && !isLoading && (
            <li className="text-sm text-gray-500 px-3 py-2">No projects.</li>
          )}
          {filtered.map((p) => (
            <li key={p.id}>
              <Link
                to={`/pipeline/projects/${p.id}/sources`}
                onClick={() => onSelectProject(p.id)}
                className={projectLinkClass(p.id === activeProjectId)}
                title={p.slug}
              >
                {p.name}
              </Link>
            </li>
          ))}
        </ul>
      </div>
    </aside>
  );
}
