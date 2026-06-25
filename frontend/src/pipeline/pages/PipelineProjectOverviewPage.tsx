import { Link, useNavigate, useParams } from "react-router-dom";
import { PageHeader } from "../../components/PageHeader";
import {
  usePipelineProject,
  usePipelineProjectBinding,
  usePipelineSources,
} from "../hooks/usePipeline";

export function PipelineProjectOverviewPage() {
  const { projectId } = useParams<{ projectId: string }>();
  const navigate = useNavigate();
  const { data: project, isLoading, isError } = usePipelineProject(projectId);
  const { data: binding } = usePipelineProjectBinding(projectId);
  const { data: sourcesData } = usePipelineSources(projectId);
  const sourceCount = sourcesData?.items.length ?? 0;

  if (!projectId) {
    return <p className="text-sm text-red-600">Missing project id.</p>;
  }

  if (isLoading) {
    return <p className="text-sm text-gray-500">Loading…</p>;
  }

  if (isError || !project) {
    return <p className="text-sm text-red-600">Project not found.</p>;
  }

  return (
    <div>
      <PageHeader title={project.name}>
        <button
          type="button"
          onClick={() => navigate(`/pipeline/projects/${projectId}/sources/new`)}
          className="text-sm bg-blue-600 hover:bg-blue-700 text-white px-3 py-1.5 rounded"
        >
          New source
        </button>
      </PageHeader>

      <p className="mb-4 text-sm text-gray-600 font-mono">{project.slug}</p>

      <div className="grid gap-4 md:grid-cols-2 mb-6">
        <div className="bg-white shadow rounded-lg p-4">
          <h3 className="text-sm font-medium text-gray-900 mb-2">Sources</h3>
          <p className="text-2xl font-semibold text-gray-900">{sourceCount}</p>
          <Link
            to={`/pipeline/projects/${projectId}/sources`}
            className="text-sm text-blue-600 hover:underline mt-2 inline-block"
          >
            Manage sources
          </Link>
        </div>
        <div className="bg-white shadow rounded-lg p-4">
          <h3 className="text-sm font-medium text-gray-900 mb-2">Documents</h3>
          <Link
            to={`/files/projects/${projectId}/documents`}
            className="text-sm text-blue-600 hover:underline"
          >
            파일관리에서 보기
          </Link>
        </div>
      </div>

      {binding && (
        <div className="bg-white shadow rounded-lg p-4">
          <h3 className="text-sm font-medium text-gray-900 mb-3">Knowledge binding</h3>
          <dl className="text-sm space-y-2">
            <div>
              <dt className="text-gray-500">Qdrant collection</dt>
              <dd className="font-mono text-xs">{binding.rag.qdrant_collection}</dd>
            </div>
            <div>
              <dt className="text-gray-500">Nebula space</dt>
              <dd className="font-mono text-xs">{binding.graph.nebula_space}</dd>
            </div>
            <div>
              <dt className="text-gray-500">Wiki prefix</dt>
              <dd className="font-mono text-xs">{binding.wiki.s3_prefix}</dd>
            </div>
          </dl>
        </div>
      )}
    </div>
  );
}
