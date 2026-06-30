function isScalar(value: unknown): value is string | number | boolean {
  const t = typeof value;
  return t === "string" || t === "number" || t === "boolean";
}

function formatUploadItem(item: Record<string, unknown>): string {
  const filename = String(item.filename ?? "file");
  const status = String(item.status ?? "unknown");
  const reason = item.reason;
  if (typeof reason === "string" && reason.trim()) {
    return `${filename}: ${status} (${reason})`;
  }
  return `${filename}: ${status}`;
}

export function formatAuditDetailValue(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (isScalar(value)) return String(value);
  if (Array.isArray(value)) {
    if (value.length === 0) return "—";
    if (value.every(isScalar)) {
      return value.map(String).join(", ");
    }
    if (
      value.every(
        (item) =>
          item !== null &&
          typeof item === "object" &&
          !Array.isArray(item) &&
          "filename" in item &&
          "status" in item,
      )
    ) {
      return value
        .map((item) => formatUploadItem(item as Record<string, unknown>))
        .join("; ");
    }
    return value.map((item) => formatAuditDetailValue(item)).join("; ");
  }
  if (typeof value === "object") {
    return JSON.stringify(value);
  }
  return String(value);
}

/** Normalize legacy audit detail keys for display. */
export function formatAuditDetailKey(key: string): string {
  if (key === "changed_fields") return "changed";
  return key;
}
