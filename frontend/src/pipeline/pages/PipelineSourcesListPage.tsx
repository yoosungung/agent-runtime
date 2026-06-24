import { Link, useNavigate } from "react-router-dom";
import { PageHeader } from "../../components/PageHeader";
import { usePipelineSources } from "../hooks/usePipeline";

function formatDate(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString();
}

export function PipelineSourcesListPage() {
  const navigate = useNavigate();
  const { data, isLoading, isError } = usePipelineSources();
  const items = data?.items ?? [];

  return (
    <div>
      <PageHeader title="Pipeline Sources">
        <button
          type="button"
          onClick={() => navigate("/pipeline/sources/new")}
          className="text-sm bg-blue-600 hover:bg-blue-700 text-white px-3 py-1.5 rounded"
        >
          New source
        </button>
      </PageHeader>

      <p className="mb-4 text-sm text-gray-600">
        문서 수집 출처를 등록합니다. OAuth 계정은{" "}
        <a href="/pipeline/credentials" className="text-blue-600 hover:underline">
          Credentials
        </a>
        에서 먼저 연결하세요.
      </p>

      {isLoading && <p className="text-sm text-gray-500">Loading…</p>}
      {isError && (
        <p className="text-sm text-red-600">Failed to load sources.</p>
      )}

      {!isLoading && !isError && (
        <div className="bg-white shadow rounded-lg overflow-hidden">
          <table className="min-w-full text-sm">
            <thead className="bg-gray-50 text-left text-gray-600">
              <tr>
                <th className="px-4 py-2 font-medium">Name</th>
                <th className="px-4 py-2 font-medium">Driver</th>
                <th className="px-4 py-2 font-medium">Enabled</th>
                <th className="px-4 py-2 font-medium">Schedule</th>
                <th className="px-4 py-2 font-medium">Last run</th>
                <th className="px-4 py-2 font-medium">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {items.length === 0 ? (
                <tr>
                  <td colSpan={6} className="px-4 py-6 text-center text-gray-500">
                    No sources yet.{" "}
                    <Link to="/pipeline/sources/new" className="text-blue-600 hover:underline">
                      Create one
                    </Link>
                  </td>
                </tr>
              ) : (
                items.map((src) => (
                  <tr
                    key={src.id}
                    className="hover:bg-gray-50 cursor-pointer"
                    onClick={() => navigate(`/pipeline/sources/${src.id}`)}
                  >
                    <td className="px-4 py-2 font-medium text-gray-900">{src.name}</td>
                    <td className="px-4 py-2 text-gray-700">{src.driver}</td>
                    <td className="px-4 py-2">{src.enabled ? "Yes" : "No"}</td>
                    <td className="px-4 py-2 font-mono text-xs text-gray-600">
                      {src.schedule_cron ?? "—"}
                    </td>
                    <td className="px-4 py-2 text-gray-600">
                      {formatDate(src.last_run_at)}
                    </td>
                    <td className="px-4 py-2 text-gray-600">
                      {src.last_run_status ?? "—"}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      )}

      <div className="mt-4">
        <Link to="/pipeline/runs" className="text-sm text-blue-600 hover:underline">
          View runs &amp; dead letters →
        </Link>
      </div>
    </div>
  );
}
