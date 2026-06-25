import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { PageHeader } from "../../components/PageHeader";
import {
  useCreatePipelineProject,
  usePipelineProjects,
} from "../hooks/usePipeline";

export function PipelineProjectsPage() {
  const navigate = useNavigate();
  const { data, isLoading, isError } = usePipelineProjects();
  const createMut = useCreatePipelineProject();
  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");
  const [error, setError] = useState<string | null>(null);

  const items = data?.items ?? [];

  async function onCreate(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      const created = await createMut.mutateAsync({
        name: name.trim(),
        slug: slug.trim() || undefined,
      });
      setName("");
      setSlug("");
      navigate(`/pipeline/projects/${created.id}`);
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
    <div>
      <PageHeader title="Knowledge Projects" />

      <p className="mb-4 text-sm text-gray-600">
        Source·RAG·graph·wiki가 공유하는 정보 경계입니다. Project를 선택하거나 새로
        만드세요.
      </p>

      {isLoading && <p className="text-sm text-gray-500">Loading…</p>}
      {isError && <p className="text-sm text-red-600">Failed to load projects.</p>}

      {!isLoading && !isError && (
        <div className="bg-white shadow rounded-lg overflow-hidden mb-6">
          <table className="min-w-full text-sm">
            <thead className="bg-gray-50 text-left text-gray-600">
              <tr>
                <th className="px-4 py-2 font-medium">Name</th>
                <th className="px-4 py-2 font-medium">Slug</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {items.length === 0 ? (
                <tr>
                  <td colSpan={2} className="px-4 py-6 text-center text-gray-500">
                    No projects yet. Create one below.
                  </td>
                </tr>
              ) : (
                items.map((project) => (
                  <tr
                    key={project.id}
                    className="hover:bg-gray-50 cursor-pointer"
                    onClick={() => navigate(`/pipeline/projects/${project.id}`)}
                  >
                    <td className="px-4 py-2 font-medium text-gray-900">
                      <Link
                        to={`/pipeline/projects/${project.id}`}
                        className="hover:underline"
                        onClick={(e) => e.stopPropagation()}
                      >
                        {project.name}
                      </Link>
                    </td>
                    <td className="px-4 py-2 font-mono text-xs text-gray-700">
                      {project.slug}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      )}

      <div className="bg-white shadow rounded-lg p-6 max-w-xl">
        <h2 className="text-sm font-semibold text-gray-900 mb-3">New project</h2>
        {error && (
          <div className="mb-4 bg-red-50 border border-red-200 rounded px-4 py-3 text-sm text-red-700">
            {error}
          </div>
        )}
        <form onSubmit={onCreate} className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Name</label>
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="border border-gray-300 rounded px-3 py-2 w-full"
              required
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Slug <span className="text-gray-400 font-normal">(선택)</span>
            </label>
            <input
              value={slug}
              onChange={(e) => setSlug(e.target.value)}
              placeholder="product-docs"
              className="border border-gray-300 rounded px-3 py-2 w-full font-mono text-sm"
            />
          </div>
          <button
            type="submit"
            disabled={createMut.isPending}
            className="bg-blue-600 hover:bg-blue-700 text-white px-4 py-2 rounded text-sm disabled:opacity-50"
          >
            {createMut.isPending ? "Creating…" : "Create project"}
          </button>
        </form>
      </div>
    </div>
  );
}
