import { useEffect, useState } from "react";
import { usePatchSourceMeta } from "../hooks/useSourceMeta";
import { UserMetaForm } from "./UserMetaForm";
import {
  EMAIL_MCP_HELP,
  normalizeUserMetaTemplate,
  serializeUserMetaTemplateForSave,
  type UserMetaFormField,
  type UserMetaFormTemplate,
} from "../lib/userMetaTemplate";

interface Props {
  sourceMetaId: number;
  initialTemplate: UserMetaFormTemplate | Record<string, unknown>;
}

const fieldTypes = ["string", "password", "number", "boolean"] as const;

export function UserMetaTemplateTab({ sourceMetaId, initialTemplate }: Props) {
  const patchMut = usePatchSourceMeta(sourceMetaId);
  const [template, setTemplate] = useState<UserMetaFormTemplate>(() =>
    normalizeUserMetaTemplate(initialTemplate),
  );
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saveSuccess, setSaveSuccess] = useState(false);
  const [helpOpen, setHelpOpen] = useState(false);
  const [initialized, setInitialized] = useState(false);

  useEffect(() => {
    if (!initialized) {
      setTemplate(normalizeUserMetaTemplate(initialTemplate));
      setInitialized(true);
    }
  }, [initialTemplate, initialized]);

  function updateField(index: number, patch: Partial<UserMetaFormField>) {
    setTemplate((prev) => {
      const fields = [...(prev.fields ?? [])];
      fields[index] = { ...fields[index], ...patch };
      return { ...prev, fields };
    });
  }

  function addField() {
    setTemplate((prev) => ({
      ...prev,
      fields: [
        ...(prev.fields ?? []),
        { path: "", label: "", type: "string", required: false },
      ],
    }));
  }

  function removeField(index: number) {
    setTemplate((prev) => ({
      ...prev,
      fields: (prev.fields ?? []).filter((_, i) => i !== index),
    }));
  }

  async function handleSave() {
    setSaveError(null);
    setSaveSuccess(false);
    try {
      await patchMut.mutateAsync({
        user_meta_template: serializeUserMetaTemplateForSave(template),
      });
      setSaveSuccess(true);
    } catch (e: unknown) {
      const err = e as { message?: string; body?: { detail?: unknown } };
      const detail = err.body?.detail;
      if (Array.isArray(detail)) {
        setSaveError(detail.map((item) => JSON.stringify(item)).join("; "));
      } else if (typeof detail === "string") {
        setSaveError(detail);
      } else {
        setSaveError(err.message ?? "Save failed");
      }
    }
  }

  return (
    <div className="space-y-6">
      <div className="rounded-lg border border-blue-100 bg-blue-50 px-4 py-3 text-sm text-blue-900">
        <p className="font-medium mb-1">User Meta Template</p>
        <p className="text-blue-800">
          사용자가 <code className="text-xs bg-blue-100 px-1 rounded">/me</code>에서
          입력할 양식을 정의합니다. 실제 credential은 사용자 본인만 저장합니다.
        </p>
      </div>

      <div className="border border-gray-200 rounded-lg p-4 space-y-3">
        <label className="flex items-center gap-2 text-sm font-medium text-gray-900">
          <input
            type="checkbox"
            checked={Boolean(template.enabled)}
            onChange={(e) => {
              if (e.target.checked) {
                setTemplate((prev) => ({ ...prev, enabled: true }));
              } else {
                setTemplate((prev) => ({
                  ...prev,
                  enabled: false,
                  fields: [],
                  secrets_ref_enabled: false,
                }));
              }
            }}
          />
          User meta required
        </label>
        {!template.enabled && (
          <p className="text-sm text-gray-500">
            This resource is hidden from user Integrations — no per-user configuration
            is needed.
          </p>
        )}
      </div>

      {template.enabled && (
      <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
        <div className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Description (shown to users)
            </label>
            <textarea
              value={template.description ?? ""}
              onChange={(e) =>
                setTemplate((prev) => ({ ...prev, description: e.target.value }))
              }
              rows={3}
              className="border border-gray-300 rounded px-3 py-2 w-full focus:outline-none focus:ring-2 focus:ring-blue-500 text-sm"
              placeholder="Explain what users need to configure..."
            />
          </div>

          <div>
            <div className="flex items-center justify-between mb-2">
              <h3 className="text-sm font-semibold text-gray-900">Form fields</h3>
              <button
                type="button"
                onClick={addField}
                className="text-sm text-blue-600 hover:underline"
              >
                + Add field
              </button>
            </div>

            {(template.fields ?? []).length === 0 ? (
              <p className="text-sm text-gray-500 border border-dashed border-gray-300 rounded p-4">
                No fields yet. Users will see a generic JSON editor until you add fields.
              </p>
            ) : (
              <div className="space-y-3">
                {(template.fields ?? []).map((field, index) => (
                  <div
                    key={index}
                    className="border border-gray-200 rounded-lg p-3 space-y-2 bg-gray-50"
                  >
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                      <input
                        value={field.path}
                        onChange={(e) => updateField(index, { path: e.target.value })}
                        placeholder="path e.g. outlook.mailbox"
                        className="border border-gray-300 rounded px-2 py-1.5 text-sm"
                      />
                      <input
                        value={field.label}
                        onChange={(e) => updateField(index, { label: e.target.value })}
                        placeholder="Label"
                        className="border border-gray-300 rounded px-2 py-1.5 text-sm"
                      />
                    </div>
                    <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
                      <select
                        value={field.type ?? "string"}
                        onChange={(e) =>
                          updateField(index, {
                            type: e.target.value as UserMetaFormField["type"],
                          })
                        }
                        className="border border-gray-300 rounded px-2 py-1.5 text-sm"
                      >
                        {fieldTypes.map((t) => (
                          <option key={t} value={t}>
                            {t}
                          </option>
                        ))}
                      </select>
                      <input
                        value={field.placeholder ?? ""}
                        onChange={(e) =>
                          updateField(index, { placeholder: e.target.value })
                        }
                        placeholder="Placeholder"
                        className="border border-gray-300 rounded px-2 py-1.5 text-sm"
                      />
                      <label className="flex items-center gap-2 text-sm text-gray-700 px-1">
                        <input
                          type="checkbox"
                          checked={field.required ?? false}
                          onChange={(e) =>
                            updateField(index, { required: e.target.checked })
                          }
                        />
                        Required
                      </label>
                    </div>
                    <input
                      value={field.help ?? ""}
                      onChange={(e) => updateField(index, { help: e.target.value })}
                      placeholder="Help text"
                      className="border border-gray-300 rounded px-2 py-1.5 text-sm w-full"
                    />
                    <button
                      type="button"
                      onClick={() => removeField(index)}
                      className="text-xs text-red-600 hover:underline"
                    >
                      Remove field
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>

          <div className="border border-gray-200 rounded-lg p-3 space-y-2">
            <label className="flex items-center gap-2 text-sm font-medium text-gray-700">
              <input
                type="checkbox"
                checked={template.secrets_ref_enabled ?? false}
                onChange={(e) =>
                  setTemplate((prev) => ({
                    ...prev,
                    secrets_ref_enabled: e.target.checked,
                  }))
                }
              />
              Include secrets_ref field
            </label>
            {template.secrets_ref_enabled && (
              <input
                value={template.secrets_ref_help ?? ""}
                onChange={(e) =>
                  setTemplate((prev) => ({
                    ...prev,
                    secrets_ref_help: e.target.value,
                  }))
                }
                placeholder="Help for secrets_ref"
                className="border border-gray-300 rounded px-2 py-1.5 text-sm w-full"
              />
            )}
          </div>

          <div>
            <button
              type="button"
              onClick={() => setHelpOpen((v) => !v)}
              className="text-sm text-blue-600 hover:underline"
            >
              {helpOpen ? "Hide" : "Show"} email MCP example
            </button>
            {helpOpen && (
              <pre className="mt-2 text-xs bg-gray-50 border border-gray-200 rounded p-3 overflow-x-auto text-gray-700">
                {EMAIL_MCP_HELP}
              </pre>
            )}
          </div>
        </div>

        <div className="bg-white border border-gray-200 rounded-lg p-4">
          <h3 className="text-sm font-semibold text-gray-900 mb-3">User preview</h3>
          <UserMetaForm
            template={template}
            value={{}}
            onChange={() => {}}
            secretsRef=""
            onSecretsRefChange={() => {}}
            readOnly
          />
        </div>
      </div>
      )}

      {!template.enabled && (
        <div className="bg-white border border-gray-200 rounded-lg p-4">
          <h3 className="text-sm font-semibold text-gray-900 mb-2">User preview</h3>
          <p className="text-sm text-gray-500">
            Users will not be prompted to configure settings for this resource.
          </p>
        </div>
      )}

      {saveError && (
        <p className="text-sm text-red-600 bg-red-50 border border-red-200 rounded px-3 py-2">
          {saveError}
        </p>
      )}
      {saveSuccess && (
        <p className="text-sm text-green-600 bg-green-50 border border-green-200 rounded px-3 py-2">
          Template saved.
        </p>
      )}

      <button
        type="button"
        onClick={handleSave}
        disabled={patchMut.isPending}
        className="bg-blue-600 text-white px-4 py-2 rounded hover:bg-blue-700 disabled:opacity-50 text-sm font-medium"
      >
        {patchMut.isPending ? "Saving..." : "Save template"}
      </button>
    </div>
  );
}
