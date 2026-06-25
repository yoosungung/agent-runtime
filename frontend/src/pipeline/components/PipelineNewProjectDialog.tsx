import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useCreatePipelineProject } from "../hooks/usePipeline";
import { useKnowledgeProjectContext } from "../../knowledge/context/KnowledgeProjectContext";

type Props = {
  open: boolean;
  onClose: () => void;
};

export function PipelineNewProjectDialog({ open, onClose }: Props) {
  const navigate = useNavigate();
  const { setSelectedProjectId } = useKnowledgeProjectContext();
  const createMut = useCreatePipelineProject();
  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");
  const [error, setError] = useState<string | null>(null);

  if (!open) return null;

  function resetAndClose() {
    setName("");
    setSlug("");
    setError(null);
    onClose();
  }

  async function onCreate(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      const created = await createMut.mutateAsync({
        name: name.trim(),
        slug: slug.trim() || undefined,
      });
      resetAndClose();
      setSelectedProjectId(created.id);
      navigate(`/pipeline/projects/${created.id}/sources`);
    } catch (err: unknown) {
      const status = (err as { status?: number })?.status;
      if (status === 409) {
        setError("Project slug already exists for this tenant.");
      } else {
        setError(err instanceof Error ? err.message : "Failed to create project");
      }
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div className="absolute inset-0 bg-black/50" onClick={resetAndClose} />
      <div
        role="dialog"
        aria-labelledby="new-project-title"
        className="relative bg-white rounded-lg shadow-xl p-6 max-w-md w-full mx-4 z-10"
      >
        <h2 id="new-project-title" className="text-lg font-semibold text-gray-900 mb-4">
          New project
        </h2>
        {error && (
          <div className="mb-4 bg-red-50 border border-red-200 rounded px-4 py-3 text-sm text-red-700">
            {error}
          </div>
        )}
        <form onSubmit={onCreate} className="space-y-4">
          <div>
            <label htmlFor="new-project-name" className="block text-sm font-medium text-gray-700 mb-1">
              Name
            </label>
            <input
              id="new-project-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="border border-gray-300 rounded px-3 py-2 w-full"
              required
              autoFocus
            />
          </div>
          <div>
            <label htmlFor="new-project-slug" className="block text-sm font-medium text-gray-700 mb-1">
              Slug <span className="text-gray-400 font-normal">(선택)</span>
            </label>
            <input
              id="new-project-slug"
              value={slug}
              onChange={(e) => setSlug(e.target.value)}
              placeholder="product-docs"
              className="border border-gray-300 rounded px-3 py-2 w-full font-mono text-sm"
            />
          </div>
          <div className="flex justify-end gap-3 pt-2">
            <button
              type="button"
              onClick={resetAndClose}
              className="px-4 py-2 rounded border border-gray-300 text-sm hover:bg-gray-50"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={createMut.isPending}
              className="bg-blue-600 hover:bg-blue-700 text-white px-4 py-2 rounded text-sm disabled:opacity-50"
            >
              {createMut.isPending ? "Creating…" : "Create project"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
