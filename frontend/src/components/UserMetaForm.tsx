import { JsonEditor } from "./JsonEditor";
import {
  getNestedValue,
  hasTemplateFields,
  isUserMetaRequired,
  parseUserMetaTemplate,
  setNestedValue,
  type UserMetaFormTemplate,
} from "../lib/userMetaTemplate";

interface Props {
  template: UserMetaFormTemplate | Record<string, unknown>;
  value: Record<string, unknown>;
  onChange: (value: Record<string, unknown>) => void;
  secretsRef: string;
  onSecretsRefChange: (value: string) => void;
  readOnly?: boolean;
}

const inputClassName =
  "border border-gray-300 rounded px-3 py-2 w-full focus:outline-none focus:ring-2 focus:ring-blue-500 text-sm";

export function UserMetaForm({
  template: rawTemplate,
  value,
  onChange,
  secretsRef,
  onSecretsRefChange,
  readOnly = false,
}: Props) {
  const template = parseUserMetaTemplate(rawTemplate);
  const fields = template.fields ?? [];

  if (!isUserMetaRequired(template)) {
    return (
      <p className="text-sm text-gray-500">
        User-specific settings are not required for this resource.
      </p>
    );
  }

  if (!hasTemplateFields(template)) {
    return (
      <div className="space-y-4">
        {template.description && (
          <p className="text-sm text-gray-600 whitespace-pre-wrap">{template.description}</p>
        )}
        <JsonEditor value={value} onChange={readOnly ? () => {} : onChange} readOnly={readOnly} />
        {!readOnly && (
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Secrets Ref
            </label>
            <input
              type="text"
              value={secretsRef}
              onChange={(e) => onSecretsRefChange(e.target.value)}
              placeholder="vault://secret/path or env://VAR_NAME"
              className={inputClassName}
            />
          </div>
        )}
      </div>
    );
  }

  function updateField(path: string, fieldValue: unknown) {
    onChange(setNestedValue(value, path, fieldValue));
  }

  return (
    <div className="space-y-4">
      {template.description && (
        <p className="text-sm text-gray-600 whitespace-pre-wrap">{template.description}</p>
      )}

      {fields.map((field) => {
        const fieldType = field.type ?? "string";
        const current = getNestedValue(value, field.path);
        const label = (
          <>
            {field.label}
            {field.required && <span className="text-red-500 ml-0.5">*</span>}
          </>
        );

        if (fieldType === "boolean") {
          return (
            <div key={field.path}>
              <label className="flex items-center gap-2 text-sm font-medium text-gray-700">
                <input
                  type="checkbox"
                  checked={Boolean(current)}
                  disabled={readOnly}
                  onChange={(e) => updateField(field.path, e.target.checked)}
                />
                {label}
              </label>
              {field.help && <p className="text-xs text-gray-500 mt-1">{field.help}</p>}
            </div>
          );
        }

        return (
          <div key={field.path}>
            <label className="block text-sm font-medium text-gray-700 mb-1">{label}</label>
            <input
              type={fieldType === "password" ? "password" : fieldType === "number" ? "number" : "text"}
              value={current === undefined || current === null ? "" : String(current)}
              disabled={readOnly}
              placeholder={field.placeholder ?? field.path}
              onChange={(e) => {
                const raw = e.target.value;
                if (fieldType === "number") {
                  updateField(field.path, raw === "" ? "" : Number(raw));
                } else {
                  updateField(field.path, raw);
                }
              }}
              className={inputClassName}
            />
            {field.help && <p className="text-xs text-gray-500 mt-1">{field.help}</p>}
          </div>
        );
      })}

      {template.secrets_ref_enabled && (
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">
            Secrets Ref
          </label>
          <input
            type="text"
            value={secretsRef}
            disabled={readOnly}
            onChange={(e) => onSecretsRefChange(e.target.value)}
            placeholder="vault://secret/path or env://VAR_NAME"
            className={inputClassName}
          />
          {template.secrets_ref_help && (
            <p className="text-xs text-gray-500 mt-1">{template.secrets_ref_help}</p>
          )}
        </div>
      )}
    </div>
  );
}
