import { useNavigate, useParams } from "react-router-dom";
import { usePipelineProjects } from "../../pipeline/hooks/usePipeline";
import { useKnowledgeProjectContext } from "../context/KnowledgeProjectContext";

type Props = {
  basePath: "pipeline" | "files";
};

export function ProjectSwitcher({ basePath }: Props) {
  const navigate = useNavigate();
  const { projectId: routeProjectId } = useParams<{ projectId?: string }>();
  const { selectedProjectId, setSelectedProjectId } = useKnowledgeProjectContext();
  const { data, isLoading } = usePipelineProjects();
  const projects = data?.items ?? [];

  const currentId = routeProjectId ?? selectedProjectId ?? "";

  function onChange(nextId: string) {
    if (!nextId) return;
    setSelectedProjectId(nextId);
    if (basePath === "pipeline") {
      navigate(`/pipeline/projects/${nextId}`);
    } else {
      navigate(`/files/projects/${nextId}/documents`);
    }
  }

  return (
    <div className="mb-4">
      <label className="block text-xs font-medium text-gray-500 mb-1">Project</label>
      <select
        value={currentId}
        onChange={(e) => onChange(e.target.value)}
        disabled={isLoading || projects.length === 0}
        className="w-full border border-gray-300 rounded px-2 py-1.5 text-sm bg-white"
      >
        <option value="">Select project…</option>
        {projects.map((p) => (
          <option key={p.id} value={p.id}>
            {p.name}
          </option>
        ))}
      </select>
    </div>
  );
}
