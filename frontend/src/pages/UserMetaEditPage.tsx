import { useState, useEffect } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { useSourceMetaById } from "../hooks/useSourceMeta";
import { useUserMeta, useUpsertUserMeta } from "../hooks/useUserMeta";
import { JsonEditor } from "../components/JsonEditor";
import { mergeConfigs, getDiffKeys } from "../lib/mergeConfigs";

export function UserMetaEditPage() {
  const { sourceMetaId, principal } = useParams<{
    sourceMetaId: string;
    principal: string;
  }>();
  const navigate = useNavigate();
  const numSourceMetaId = Number(sourceMetaId);
  const decodedPrincipal = decodeURIComponent(principal ?? "");

  const { data: sourceMeta } = useSourceMetaById(numSourceMetaId);
  const { data: userMeta } = useUserMeta(numSourceMetaId, decodedPrincipal);
  const upsertMut = useUpsertUserMeta();

  const [userConfig, setUserConfig] = useState<Record<string, unknown>>({});
  const [secretsRef, setSecretsRef] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);
  const [initialized, setInitialized] = useState(false);

  useEffect(() => {
    if (!initialized && userMeta) {
      setUserConfig(userMeta.config ?? {});
      setSecretsRef(userMeta.secrets_ref ?? "");
      setInitialized(true);
    }
  }, [userMeta, initialized]);

  const sourceConfig = sourceMeta?.config ?? {};
  const merged = mergeConfigs(sourceConfig, userConfig);
  const diffKeys = getDiffKeys(sourceConfig, userConfig);

  async function handleSave() {
    setError(null);
    setSuccess(false);
    try {
      await upsertMut.mutateAsync({
        source_meta_id: numSourceMetaId,
        principal_id: decodedPrincipal,
        config: userConfig,
        secrets_ref: secretsRef || null,
      });
      setSuccess(true);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Save failed");
    }
  }

  function handleBack() {
    navigate(-1);
  }

  return (
    <div>
      <div className="flex items-center gap-2 mb-6">
        <button
          onClick={handleBack}
          className="text-sm text-blue-600 hover:underline"
        >
          Back
        </button>
        <span className="text-gray-400">/</span>
        <h1 className="text-2xl font-bold text-gray-900">
          User Meta — {decodedPrincipal}
        </h1>
      </div>

      {sourceMeta && (
        <p className="text-sm text-gray-500 mb-4">
          Resource:{" "}
          <span className="font-medium">
            {sourceMeta.name} @ {sourceMeta.version}
          </span>
        </p>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-6">
        <div className="bg-white shadow rounded-lg p-6">
          <h2 className="text-base font-semibold text-gray-700 mb-3">
            Source Config{" "}
            <span className="text-xs font-normal text-gray-400">(read-only)</span>
          </h2>
          <JsonEditor
            value={sourceConfig}
            onChange={() => {}}
            readOnly
          />
        </div>

        <div className="bg-white shadow rounded-lg p-6">
          <h2 className="text-base font-semibold text-gray-700 mb-3">
            User Config{" "}
            <span className="text-xs font-normal text-gray-400">
              (user overrides)
            </span>
          </h2>
          <JsonEditor value={userConfig} onChange={setUserConfig} />

          <div className="mt-4">
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Secrets Ref
            </label>
            <input
              type="text"
              value={secretsRef}
              onChange={(e) => setSecretsRef(e.target.value)}
              placeholder="vault://secret/path or env://VAR_NAME"
              className="border border-gray-300 rounded px-3 py-2 w-full focus:outline-none focus:ring-2 focus:ring-blue-500 text-sm"
            />
          </div>
        </div>
      </div>

      {/* Merge preview */}
      <div className="bg-white shadow rounded-lg p-6 mb-6">
        <h2 className="text-base font-semibold text-gray-700 mb-3">
          Merge Preview{" "}
          <span className="text-xs font-normal text-gray-400">
            (user wins on conflict)
          </span>
        </h2>
        {diffKeys.length === 0 ? (
          <p className="text-sm text-gray-400">
            Both configs are empty. Nothing to merge.
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-200 text-sm">
              <thead>
                <tr>
                  <th className="bg-gray-50 px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">
                    Key
                  </th>
                  <th className="bg-gray-50 px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">
                    Source Value
                  </th>
                  <th className="bg-gray-50 px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">
                    User Value
                  </th>
                  <th className="bg-gray-50 px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">
                    Merged Value
                  </th>
                  <th className="bg-gray-50 px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">
                    State
                  </th>
                </tr>
              </thead>
              <tbody className="bg-white divide-y divide-gray-200">
                {diffKeys.map((dk) => (
                  <tr
                    key={dk.key}
                    className={
                      dk.state === "overridden"
                        ? "bg-yellow-50"
                        : dk.state === "user-only"
                          ? "bg-blue-50"
                          : ""
                    }
                  >
                    <td className="px-4 py-2 font-mono font-medium">
                      {dk.key}
                    </td>
                    <td className="px-4 py-2 text-gray-500 font-mono">
                      {dk.sourceValue !== undefined
                        ? JSON.stringify(dk.sourceValue)
                        : "–"}
                    </td>
                    <td className="px-4 py-2 text-gray-500 font-mono">
                      {dk.userValue !== undefined
                        ? JSON.stringify(dk.userValue)
                        : "–"}
                    </td>
                    <td className="px-4 py-2 font-mono">
                      {JSON.stringify(merged[dk.key])}
                    </td>
                    <td className="px-4 py-2">
                      <span
                        className={`text-xs font-medium px-2 py-0.5 rounded ${
                          dk.state === "overridden"
                            ? "bg-yellow-100 text-yellow-800"
                            : dk.state === "user-only"
                              ? "bg-blue-100 text-blue-800"
                              : "bg-gray-100 text-gray-600"
                        }`}
                      >
                        {dk.state}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
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

      <div className="flex gap-3">
        <button
          onClick={handleSave}
          disabled={upsertMut.isPending}
          className="bg-blue-600 text-white px-4 py-2 rounded hover:bg-blue-700 disabled:opacity-50"
        >
          {upsertMut.isPending ? "Saving..." : "Save"}
        </button>
        <button
          onClick={handleBack}
          className="px-4 py-2 rounded border border-gray-300 hover:bg-gray-50"
        >
          Cancel
        </button>
      </div>
    </div>
  );
}
