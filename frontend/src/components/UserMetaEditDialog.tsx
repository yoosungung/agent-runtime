import { useState, useEffect } from "react";
import { useMyUserMeta, useUpsertMyUserMeta } from "../hooks/useMyUserMeta";
import { UserMetaForm } from "./UserMetaForm";
import { EMAIL_MCP_HELP, isUserMetaRequired } from "../lib/userMetaTemplate";

interface Props {
  open: boolean;
  kind: "agent" | "mcp";
  name: string;
  onClose: () => void;
}

export function UserMetaEditDialog({ open, kind, name, onClose }: Props) {
  const { data, isLoading, isError } = useMyUserMeta(
    open ? kind : undefined,
    open ? name : undefined,
  );
  const upsertMut = useUpsertMyUserMeta();

  const [userConfig, setUserConfig] = useState<Record<string, unknown>>({});
  const [secretsRef, setSecretsRef] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);
  const [initialized, setInitialized] = useState(false);
  const [helpOpen, setHelpOpen] = useState(false);

  useEffect(() => {
    if (!open) {
      setInitialized(false);
      setUserConfig({});
      setSecretsRef("");
      setError(null);
      setSuccess(false);
      setHelpOpen(false);
    }
  }, [open, kind, name]);

  useEffect(() => {
    if (!initialized && data) {
      setUserConfig(data.config ?? {});
      setSecretsRef(data.secrets_ref ?? "");
      setInitialized(true);
    }
  }, [data, initialized]);

  async function handleSave() {
    setError(null);
    setSuccess(false);
    try {
      await upsertMut.mutateAsync({
        kind,
        name,
        config: userConfig,
        secrets_ref: secretsRef || null,
      });
      setSuccess(true);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Save failed");
    }
  }

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-black/50" onClick={onClose} />
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="user-meta-dialog-title"
        className="relative bg-white rounded-lg shadow-xl w-full max-w-2xl max-h-[90vh] overflow-y-auto z-10"
      >
        <div className="p-6">
          <div className="flex items-start justify-between gap-4 mb-4">
            <div>
              <h2
                id="user-meta-dialog-title"
                className="text-lg font-semibold text-gray-900"
              >
                {name}
              </h2>
              {data && (
                <p className="text-sm text-gray-500 mt-0.5">@ {data.version}</p>
              )}
            </div>
            <button
              type="button"
              onClick={onClose}
              className="text-gray-400 hover:text-gray-600 text-xl leading-none"
              aria-label="Close"
            >
              ×
            </button>
          </div>

          {isLoading && (
            <p className="text-sm text-gray-500">Loading...</p>
          )}

          {isError && (
            <p className="text-sm text-red-600">Failed to load settings.</p>
          )}

          {!isLoading && !isError && data && (
            <>
              {!isUserMetaRequired(data.user_meta_template) ? (
                <>
                  <p className="text-sm text-gray-600 mb-6">
                    User-specific settings are not required for this resource.
                  </p>
                  <div className="flex justify-end">
                    <button
                      type="button"
                      onClick={onClose}
                      className="px-4 py-2 rounded border border-gray-300 text-sm hover:bg-gray-50"
                    >
                      Close
                    </button>
                  </div>
                </>
              ) : (
                <>
              <div className="mb-4">
                <button
                  type="button"
                  onClick={() => setHelpOpen((v) => !v)}
                  className="text-sm text-blue-600 hover:underline"
                >
                  {helpOpen ? "Hide" : "Show"} email MCP example (source vs user)
                </button>
                {helpOpen && (
                  <pre className="mt-2 text-xs bg-gray-50 border border-gray-200 rounded p-3 overflow-x-auto text-gray-700">
                    {EMAIL_MCP_HELP}
                  </pre>
                )}
              </div>

              <div className="mb-4">
                <h3 className="text-sm font-semibold text-gray-700 mb-3">
                  Your Settings
                </h3>
                <UserMetaForm
                  template={data.user_meta_template}
                  value={userConfig}
                  onChange={setUserConfig}
                  secretsRef={secretsRef}
                  onSecretsRefChange={setSecretsRef}
                />
              </div>

              {error && (
                <div className="mb-4 bg-red-50 border border-red-200 rounded px-4 py-3 text-sm text-red-700">
                  {error}
                </div>
              )}
              {success && (
                <div className="mb-4 bg-green-50 border border-green-200 rounded px-4 py-3 text-sm text-green-700">
                  Saved successfully.
                </div>
              )}

              <div className="flex justify-end gap-3">
                <button
                  type="button"
                  onClick={onClose}
                  className="px-4 py-2 rounded border border-gray-300 text-sm hover:bg-gray-50"
                >
                  Cancel
                </button>
                <button
                  type="button"
                  onClick={handleSave}
                  disabled={upsertMut.isPending}
                  className="bg-blue-600 text-white px-4 py-2 rounded hover:bg-blue-700 disabled:opacity-50 text-sm"
                >
                  {upsertMut.isPending ? "Saving..." : "Save"}
                </button>
              </div>
                </>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
