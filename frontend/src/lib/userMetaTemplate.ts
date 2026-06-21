export type UserMetaFieldType = "string" | "password" | "number" | "boolean";

export interface UserMetaFormField {
  path: string;
  label: string;
  type?: UserMetaFieldType;
  required?: boolean;
  placeholder?: string;
  help?: string;
}

export interface UserMetaFormTemplate {
  enabled?: boolean | null;
  description?: string | null;
  fields?: UserMetaFormField[];
  secrets_ref_enabled?: boolean;
  secrets_ref_help?: string | null;
}

export function isUserMetaRequired(template: UserMetaFormTemplate): boolean {
  if (template.enabled !== undefined && template.enabled !== null) {
    return template.enabled;
  }
  return (template.fields?.length ?? 0) > 0 || Boolean(template.secrets_ref_enabled);
}

export function normalizeUserMetaTemplate(raw: unknown): UserMetaFormTemplate {
  const parsed = parseUserMetaTemplate(raw);
  const fields = [...(parsed.fields ?? [])];
  const enabled =
    parsed.enabled !== undefined && parsed.enabled !== null
      ? parsed.enabled
      : fields.length > 0 || Boolean(parsed.secrets_ref_enabled);

  return {
    ...emptyUserMetaTemplate(),
    ...parsed,
    enabled,
    fields,
  };
}

export function parseUserMetaTemplate(raw: unknown): UserMetaFormTemplate {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) {
    return {};
  }
  return raw as UserMetaFormTemplate;
}

export function hasTemplateFields(template: UserMetaFormTemplate): boolean {
  if (!isUserMetaRequired(template)) {
    return false;
  }
  return (template.fields?.length ?? 0) > 0 || Boolean(template.secrets_ref_enabled);
}

export function getNestedValue(
  config: Record<string, unknown>,
  path: string,
): unknown {
  const parts = path.split(".");
  let current: unknown = config;
  for (const part of parts) {
    if (!current || typeof current !== "object" || Array.isArray(current)) {
      return undefined;
    }
    current = (current as Record<string, unknown>)[part];
  }
  return current;
}

export function setNestedValue(
  config: Record<string, unknown>,
  path: string,
  value: unknown,
): Record<string, unknown> {
  const parts = path.split(".");
  const next = { ...config };
  let cursor: Record<string, unknown> = next;

  for (let i = 0; i < parts.length - 1; i++) {
    const part = parts[i];
    const existing = cursor[part];
    const branch =
      existing && typeof existing === "object" && !Array.isArray(existing)
        ? { ...(existing as Record<string, unknown>) }
        : {};
    cursor[part] = branch;
    cursor = branch;
  }

  const leaf = parts[parts.length - 1];
  if (value === "" || value === undefined) {
    delete cursor[leaf];
  } else {
    cursor[leaf] = value;
  }
  return next;
}

export function serializeUserMetaTemplateForSave(
  template: UserMetaFormTemplate,
): Record<string, unknown> {
  if (!template.enabled) {
    return { enabled: false };
  }

  const payload: Record<string, unknown> = {
    enabled: true,
    fields: (template.fields ?? [])
      .filter((field) => field.path.trim() && field.label.trim())
      .map((field) => ({
        path: field.path.trim(),
        label: field.label.trim(),
        type: field.type ?? "string",
        required: field.required ?? false,
        ...(field.placeholder?.trim()
          ? { placeholder: field.placeholder.trim() }
          : {}),
        ...(field.help?.trim() ? { help: field.help.trim() } : {}),
      })),
    secrets_ref_enabled: template.secrets_ref_enabled ?? false,
  };

  const description = template.description?.trim();
  if (description) {
    payload.description = description;
  }

  const secretsRefHelp = template.secrets_ref_help?.trim();
  if (secretsRefHelp) {
    payload.secrets_ref_help = secretsRefHelp;
  }

  return payload;
}

export function emptyUserMetaTemplate(): UserMetaFormTemplate {
  return {
    enabled: false,
    description: "",
    fields: [],
    secrets_ref_enabled: false,
    secrets_ref_help: "",
  };
}

export const EMAIL_MCP_HELP = `// source_meta — provider + app registration (기동)
{ "email": { "provider": "outlook" },
  "outlook": { "tenant_id": "...", "client_id": "...", "client_secret": "..." } }

// user_meta — mailbox identity (invoke, this principal)
{ "email": { "from_address": "hong@company.com" },
  "outlook": { "mailbox": "hong@company.com", "refresh_token": "..." } }`;
