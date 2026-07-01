import type { KnowledgeBinding } from "../pipeline/hooks/usePipeline";
import {
  useKnowledgeProjectBinding,
  useKnowledgeProjects,
} from "../hooks/useKnowledgeProjects";

interface Props {
  selectedIds: string[];
  onChange: (ids: string[]) => void;
  disabled?: boolean;
}

function BindingPreview({ projectId }: { projectId: string }) {
  const { data: binding } = useKnowledgeProjectBinding(projectId);
  if (!binding) return null;
  return (
    <dl className="text-xs text-gray-600 mt-1 ml-6 space-y-1">
      <div>
        <dt className="inline text-gray-500">Qdrant: </dt>
        <dd className="inline font-mono">{binding.rag.qdrant_collection}</dd>
      </div>
      <div>
        <dt className="inline text-gray-500">Nebula: </dt>
        <dd className="inline font-mono">{binding.graph.nebula_space}</dd>
      </div>
      <div>
        <dt className="inline text-gray-500">Wiki: </dt>
        <dd className="inline font-mono">{binding.wiki.s3_prefix}</dd>
      </div>
    </dl>
  );
}

export function GeneralAgentKnowledgeProjectsField({
  selectedIds,
  onChange,
  disabled = false,
}: Props) {
  const { data, isLoading, isError } = useKnowledgeProjects();
  const projects = data?.items ?? [];

  function toggle(id: string) {
    if (disabled) return;
    onChange(
      selectedIds.includes(id)
        ? selectedIds.filter((x) => x !== id)
        : [...selectedIds, id],
    );
  }

  return (
    <div>
      <label className="block text-sm font-medium text-gray-700 mb-2">
        Pipeline projects
      </label>
      <p className="text-xs text-gray-500 mb-2">
        Knowledge boundary for retrieval MCP and wiki VFS. Required when a
        selected MCP declares pipeline project binding.
      </p>
      {isLoading ? (
        <p className="text-sm text-gray-500">Loading projects…</p>
      ) : isError ? (
        <p className="text-sm text-red-600">Failed to load pipeline projects.</p>
      ) : projects.length === 0 ? (
        <p className="text-sm text-gray-500">
          No pipeline projects yet. Create one under Pipeline first.
        </p>
      ) : (
        <div className="space-y-2 border border-gray-200 rounded p-3 max-h-64 overflow-y-auto">
          {projects.map((project) => (
            <div key={project.id}>
              <label className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={selectedIds.includes(project.id)}
                  disabled={disabled}
                  onChange={() => toggle(project.id)}
                />
                <span className="font-medium">{project.name}</span>
                <span className="text-gray-400 text-xs">{project.slug}</span>
              </label>
              {selectedIds.includes(project.id) && (
                <BindingPreview projectId={project.id} />
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export type { KnowledgeBinding };
