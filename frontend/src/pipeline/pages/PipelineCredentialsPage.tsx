import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { PageHeader } from "../../components/PageHeader";
import {
  useCreatePipelineCredential,
  useDeletePipelineCredential,
  usePipelineCredentials,
  useStartPipelineOAuth,
} from "../hooks/usePipelineCredentials";
import type { SourceDriver } from "../hooks/usePipeline";

const DRIVERS: { value: SourceDriver; label: string }[] = [
  { value: "gdrive", label: "Google Drive" },
  { value: "sharepoint", label: "SharePoint" },
  { value: "onedrive", label: "OneDrive" },
];

function statusBadge(status: string) {
  if (status === "connected") {
    return <span className="text-green-700">connected</span>;
  }
  if (status === "error") {
    return <span className="text-red-600">error</span>;
  }
  return <span className="text-gray-500">pending</span>;
}

export function PipelineCredentialsPage() {
  const [params] = useSearchParams();
  const { data, isLoading } = usePipelineCredentials();
  const createMut = useCreatePipelineCredential();
  const deleteMut = useDeletePipelineCredential();
  const oauthMut = useStartPipelineOAuth();
  const [label, setLabel] = useState("");
  const [driver, setDriver] = useState<SourceDriver>("gdrive");
  const [error, setError] = useState<string | null>(null);

  const oauthMsg = params.get("oauth");
  const oauthError = params.get("oauth_error");

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      await createMut.mutateAsync({ label: label.trim(), driver });
      setLabel("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create credential");
    }
  }

  const items = data?.items ?? [];

  return (
    <div>
      <PageHeader title="Pipeline Credentials" />

      <p className="mb-4 text-sm text-gray-600">
        Source마다 다른 계정을 연결합니다. refresh token은 K8s Secret(또는 로컬 dev
        파일)에 저장되고 DB에는 메타만 남습니다. OAuth 앱(client id/secret)은 backend{" "}
        <code className="text-xs bg-gray-100 px-1 rounded">PIPELINE_*_CLIENT_*</code>{" "}
        환경 변수로 설정합니다.
      </p>

      {oauthMsg === "connected" && (
        <div className="mb-4 bg-green-50 border border-green-200 rounded px-4 py-3 text-sm text-green-800">
          OAuth 연결이 완료되었습니다.
        </div>
      )}
      {oauthError && (
        <div className="mb-4 bg-red-50 border border-red-200 rounded px-4 py-3 text-sm text-red-700">
          OAuth 오류: {oauthError}
        </div>
      )}

      <div className="bg-white shadow rounded-lg p-6 mb-6 max-w-xl">
        <h2 className="text-sm font-medium text-gray-900 mb-3">New credential</h2>
        {error && <p className="text-sm text-red-600 mb-2">{error}</p>}
        <form onSubmit={handleCreate} className="flex flex-wrap gap-2 items-end">
          <div className="flex-1 min-w-[12rem]">
            <label className="block text-xs text-gray-500 mb-1">Label</label>
            <input
              value={label}
              onChange={(e) => setLabel(e.target.value)}
              className="border border-gray-300 rounded px-3 py-2 w-full text-sm"
              placeholder="gdrive-team-a"
              required
            />
          </div>
          <div>
            <label className="block text-xs text-gray-500 mb-1">Driver</label>
            <select
              value={driver}
              onChange={(e) => setDriver(e.target.value as SourceDriver)}
              className="border border-gray-300 rounded px-3 py-2 text-sm"
            >
              {DRIVERS.map((d) => (
                <option key={d.value} value={d.value}>
                  {d.label}
                </option>
              ))}
            </select>
          </div>
          <button
            type="submit"
            disabled={createMut.isPending}
            className="bg-blue-600 hover:bg-blue-700 text-white px-4 py-2 rounded text-sm"
          >
            Create
          </button>
        </form>
      </div>

      <p className="mb-2 text-sm">
        <Link to="/pipeline" className="text-blue-600 hover:underline">
          ← Sources
        </Link>
      </p>

      {isLoading ? (
        <p className="text-sm text-gray-500">Loading…</p>
      ) : (
        <div className="bg-white shadow rounded-lg overflow-hidden">
          <table className="min-w-full text-sm">
            <thead className="bg-gray-50 text-left text-gray-600">
              <tr>
                <th className="px-4 py-2 font-medium">Label</th>
                <th className="px-4 py-2 font-medium">Driver</th>
                <th className="px-4 py-2 font-medium">Status</th>
                <th className="px-4 py-2 font-medium">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {items.length === 0 ? (
                <tr>
                  <td colSpan={4} className="px-4 py-6 text-center text-gray-500">
                    No credentials yet.
                  </td>
                </tr>
              ) : (
                items.map((c) => (
                  <tr key={c.id}>
                    <td className="px-4 py-2 font-medium">{c.label}</td>
                    <td className="px-4 py-2">{c.driver}</td>
                    <td className="px-4 py-2">{statusBadge(c.oauth_status)}</td>
                    <td className="px-4 py-2 space-x-2">
                      {c.oauth_status !== "connected" && (
                        <button
                          type="button"
                          onClick={() => oauthMut.mutate(c.id)}
                          disabled={oauthMut.isPending}
                          className="text-blue-600 hover:underline text-sm"
                        >
                          Connect OAuth
                        </button>
                      )}
                      <button
                        type="button"
                        onClick={() => deleteMut.mutate(c.id)}
                        className="text-red-600 hover:underline text-sm"
                      >
                        Delete
                      </button>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
