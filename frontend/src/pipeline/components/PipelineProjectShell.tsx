import { Link, NavLink, Outlet, useParams } from "react-router-dom";
import { usePipelineProject } from "../hooks/usePipeline";

const tabClass = ({ isActive }: { isActive: boolean }) =>
  `px-4 py-2 text-sm border-b-2 -mb-px ${
    isActive
      ? "border-blue-600 text-blue-700 font-medium"
      : "border-transparent text-gray-600 hover:text-gray-900 hover:border-gray-300"
  }`;

export function PipelineProjectShell() {
  const { projectId } = useParams<{ projectId: string }>();
  const { data: project, isLoading, isError } = usePipelineProject(projectId);

  if (!projectId) {
    return <p className="text-sm text-red-600">Missing project id.</p>;
  }

  if (isLoading) {
    return <p className="text-sm text-gray-500">Loading…</p>;
  }

  if (isError || !project) {
    return <p className="text-sm text-red-600">Project not found.</p>;
  }

  const base = `/pipeline/projects/${projectId}`;

  return (
    <div>
      <div className="mb-6 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold text-gray-900">{project.name}</h1>
          <p className="text-sm text-gray-500 font-mono">{project.slug}</p>
        </div>
        <Link
          to={`${base}/maintenance`}
          className="text-sm text-gray-600 hover:text-gray-900 border border-gray-300 rounded px-3 py-1.5 hover:bg-gray-50"
          title="Reconcile, cleanup, tombstones, purge"
        >
          Maintenance
        </Link>
      </div>

      <nav className="flex border-b border-gray-200 mb-6">
        <NavLink to={`${base}/sources`} className={tabClass} end>
          Sources
        </NavLink>
        <NavLink to={`${base}/runs`} className={tabClass}>
          Runs
        </NavLink>
        <NavLink to={`${base}/documents`} className={tabClass}>
          Documents
        </NavLink>
      </nav>

      <Outlet />
    </div>
  );
}
