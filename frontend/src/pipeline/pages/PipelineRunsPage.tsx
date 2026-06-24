import { useState } from "react";
import { Link } from "react-router-dom";
import { PageHeader } from "../../components/PageHeader";
import {
  usePipelineDeadLetters,
  usePipelineRuns,
} from "../hooks/usePipeline";

type Tab = "runs" | "dead-letters";

export function PipelineRunsPage() {
  const [tab, setTab] = useState<Tab>("runs");
  const runsQuery = usePipelineRuns();
  const deadQuery = usePipelineDeadLetters();

  const runs = runsQuery.data?.runs ?? [];
  const recentDocs = runsQuery.data?.recent_documents ?? [];
  const deadLetters = deadQuery.data?.items ?? [];

  return (
    <div>
      <PageHeader title="Pipeline Runs" />

      <p className="mb-4 text-sm">
        <Link to="/pipeline/sources" className="text-blue-600 hover:underline">
          ← Sources
        </Link>
      </p>

      <div className="flex gap-2 mb-4 border-b border-gray-200">
        <button
          type="button"
          onClick={() => setTab("runs")}
          className={`px-3 py-2 text-sm border-b-2 -mb-px ${
            tab === "runs"
              ? "border-blue-600 text-blue-600 font-medium"
              : "border-transparent text-gray-600"
          }`}
        >
          Runs
        </button>
        <button
          type="button"
          onClick={() => setTab("dead-letters")}
          className={`px-3 py-2 text-sm border-b-2 -mb-px ${
            tab === "dead-letters"
              ? "border-blue-600 text-blue-600 font-medium"
              : "border-transparent text-gray-600"
          }`}
        >
          Dead letters
        </button>
      </div>

      {tab === "runs" && (
        <div className="space-y-6">
          <div className="bg-white shadow rounded-lg overflow-hidden">
            <table className="min-w-full text-sm">
              <thead className="bg-gray-50 text-left text-gray-600">
                <tr>
                  <th className="px-4 py-2 font-medium">Workflow</th>
                  <th className="px-4 py-2 font-medium">Batch</th>
                  <th className="px-4 py-2 font-medium">Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {runs.length === 0 ? (
                  <tr>
                    <td colSpan={3} className="px-4 py-6 text-center text-gray-500">
                      No runs yet.
                    </td>
                  </tr>
                ) : (
                  runs.map((run) => (
                    <tr key={run.id}>
                      <td className="px-4 py-2 font-mono text-xs">{run.workflow_name}</td>
                      <td className="px-4 py-2 font-mono text-xs">{run.batch_id}</td>
                      <td className="px-4 py-2">{run.status}</td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>

          <div>
            <h2 className="text-sm font-medium text-gray-900 mb-2">Recent documents</h2>
            <div className="bg-white shadow rounded-lg overflow-hidden">
              <table className="min-w-full text-sm">
                <thead className="bg-gray-50 text-left text-gray-600">
                  <tr>
                    <th className="px-4 py-2 font-medium">Source</th>
                    <th className="px-4 py-2 font-medium">State</th>
                    <th className="px-4 py-2 font-medium">Hash</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {recentDocs.length === 0 ? (
                    <tr>
                      <td colSpan={3} className="px-4 py-6 text-center text-gray-500">
                        No documents indexed yet.
                      </td>
                    </tr>
                  ) : (
                    recentDocs.map((doc) => (
                      <tr key={doc.document_id}>
                        <td className="px-4 py-2 font-mono text-xs">{doc.source_id}</td>
                        <td className="px-4 py-2">{doc.ingest_state}</td>
                        <td className="px-4 py-2 font-mono text-xs truncate max-w-xs">
                          {doc.content_hash}
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}

      {tab === "dead-letters" && (
        <div className="bg-white shadow rounded-lg overflow-hidden">
          <table className="min-w-full text-sm">
            <thead className="bg-gray-50 text-left text-gray-600">
              <tr>
                <th className="px-4 py-2 font-medium">Source</th>
                <th className="px-4 py-2 font-medium">Document</th>
                <th className="px-4 py-2 font-medium">Raw URI</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {deadQuery.isLoading ? (
                <tr>
                  <td colSpan={3} className="px-4 py-6 text-center text-gray-500">
                    Loading…
                  </td>
                </tr>
              ) : deadLetters.length === 0 ? (
                <tr>
                  <td colSpan={3} className="px-4 py-6 text-center text-gray-500">
                    No dead-letter documents.
                  </td>
                </tr>
              ) : (
                deadLetters.map((doc) => (
                  <tr key={doc.document_id}>
                    <td className="px-4 py-2 font-mono text-xs">{doc.source_id}</td>
                    <td className="px-4 py-2 font-mono text-xs">{doc.document_id}</td>
                    <td className="px-4 py-2 font-mono text-xs truncate max-w-md">
                      {doc.s3_raw_uri}
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
