import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useCustomImageList, useDeleteCustomImage, type CustomImage } from "../hooks/useCustomImages";
import { ConfirmDialog } from "../components/ConfirmDialog";

interface Props {
  kind: "agent" | "mcp";
}

function statusBadge(status: CustomImage["status"]) {
  const map: Record<string, string> = {
    active: "bg-green-100 text-green-800",
    pending: "bg-yellow-100 text-yellow-800",
    failed: "bg-red-100 text-red-800",
    retired: "bg-gray-100 text-gray-600",
  };
  return (
    <span
      className={`text-xs font-medium px-2 py-0.5 rounded ${map[status] ?? "bg-gray-100 text-gray-600"}`}
    >
      {status}
    </span>
  );
}

function formatDate(iso: string) {
  return new Date(iso).toLocaleString();
}

export function CustomImageListPage({ kind }: Props) {
  const navigate = useNavigate();
  const { data, isLoading, isError, refetch } = useCustomImageList(kind);
  const deleteMut = useDeleteCustomImage();
  const [deleteTarget, setDeleteTarget] = useState<CustomImage | null>(null);

  const title = kind === "agent" ? "Custom Agent Images" : "Custom MCP Images";
  const newPath = kind === "agent" ? "/custom-agents/new" : "/custom-mcp/new";

  const handleDelete = async () => {
    if (!deleteTarget) return;
    await deleteMut.mutateAsync({ kind: deleteTarget.kind, slug: deleteTarget.slug });
    setDeleteTarget(null);
    refetch();
  };

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold text-gray-900">{title}</h1>
        <button
          onClick={() => navigate(newPath)}
          className="bg-blue-600 text-white px-4 py-2 rounded hover:bg-blue-700 text-sm font-medium"
        >
          + Register Image
        </button>
      </div>

      <div className="bg-white shadow rounded-lg overflow-hidden">
        {isLoading && <p className="p-4 text-sm text-gray-500">Loading...</p>}
        {isError && (
          <p className="p-4 text-sm text-red-500">Failed to load data.</p>
        )}
        {!isLoading && !isError && (
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-200">
              <thead>
                <tr>
                  {["Name", "Version", "Slug", "Image URI", "Status", "Created", "Actions"].map(
                    (h) => (
                      <th
                        key={h}
                        className="bg-gray-50 px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase"
                      >
                        {h}
                      </th>
                    ),
                  )}
                </tr>
              </thead>
              <tbody className="bg-white divide-y divide-gray-200">
                {data?.length === 0 && (
                  <tr>
                    <td
                      colSpan={7}
                      className="px-4 py-8 text-sm text-gray-500 text-center"
                    >
                      No images registered.
                    </td>
                  </tr>
                )}
                {data?.map((item) => (
                  <tr key={item.id} className="hover:bg-gray-50">
                    <td className="px-4 py-3 text-sm font-medium text-gray-900">
                      {item.name}
                    </td>
                    <td className="px-4 py-3 text-sm text-gray-600">
                      {item.version}
                    </td>
                    <td className="px-4 py-3 text-sm font-mono text-gray-600">
                      {item.slug}
                    </td>
                    <td
                      className="px-4 py-3 text-sm text-gray-600 max-w-xs truncate"
                      title={item.image_uri ?? ""}
                    >
                      {item.image_uri}
                    </td>
                    <td className="px-4 py-3 text-sm">
                      {statusBadge(item.status)}
                    </td>
                    <td className="px-4 py-3 text-sm text-gray-500">
                      {formatDate(item.created_at)}
                    </td>
                    <td className="px-4 py-3 text-sm">
                      {item.status !== "retired" && (
                        <button
                          onClick={() => setDeleteTarget(item)}
                          className="text-red-600 hover:underline text-xs"
                        >
                          Retire
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <ConfirmDialog
        open={deleteTarget !== null}
        title="Retire image deployment?"
        description={
          deleteTarget
            ? `This will stop the K8s Deployment for "${deleteTarget.name} ${deleteTarget.version}" (slug: ${deleteTarget.slug}) and mark it retired. Existing traffic will be interrupted.`
            : ""
        }
        onConfirm={handleDelete}
        onCancel={() => setDeleteTarget(null)}
        confirmLabel="Retire"
        destructive
      />
    </div>
  );
}
