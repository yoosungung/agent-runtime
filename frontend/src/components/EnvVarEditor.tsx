interface Props {
  value: Record<string, string>;
  onChange: (value: Record<string, string>) => void;
  readOnly?: boolean;
}

type Row = { key: string; value: string };

function toRows(env: Record<string, string>): Row[] {
  const entries = Object.entries(env);
  if (entries.length === 0) {
    return [{ key: "", value: "" }];
  }
  return entries.map(([key, value]) => ({ key, value }));
}

function fromRows(rows: Row[]): Record<string, string> {
  const out: Record<string, string> = {};
  for (const row of rows) {
    const k = row.key.trim();
    if (!k) continue;
    out[k] = row.value;
  }
  return out;
}

export function EnvVarEditor({ value, onChange, readOnly = false }: Props) {
  const rows = toRows(value);

  function updateRow(index: number, patch: Partial<Row>) {
    const next = rows.map((row, i) => (i === index ? { ...row, ...patch } : row));
    onChange(fromRows(next));
  }

  function addRow() {
    onChange(fromRows([...rows, { key: "", value: "" }]));
  }

  function removeRow(index: number) {
    const next = rows.filter((_, i) => i !== index);
    onChange(fromRows(next.length ? next : [{ key: "", value: "" }]));
  }

  return (
    <div className="space-y-2">
      {rows.map((row, index) => (
        <div key={index} className="flex flex-col sm:flex-row gap-2">
          <input
            value={row.key}
            onChange={(e) => updateRow(index, { key: e.target.value })}
            readOnly={readOnly}
            placeholder="LOG_LEVEL"
            className="flex-1 border border-gray-300 rounded px-3 py-2 text-sm font-mono"
          />
          <input
            value={row.value}
            onChange={(e) => updateRow(index, { value: e.target.value })}
            readOnly={readOnly}
            placeholder="debug"
            className="flex-[2] border border-gray-300 rounded px-3 py-2 text-sm font-mono"
          />
          {!readOnly && (
            <button
              type="button"
              onClick={() => removeRow(index)}
              className="text-red-600 text-sm hover:underline px-2"
            >
              Remove
            </button>
          )}
        </div>
      ))}
      {!readOnly && (
        <button
          type="button"
          onClick={addRow}
          className="text-blue-600 text-sm hover:underline"
        >
          + Add variable
        </button>
      )}
    </div>
  );
}
