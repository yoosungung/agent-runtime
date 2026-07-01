import { useEffect, useRef, useState } from "react";

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
  const [rows, setRows] = useState<Row[]>(() => toRows(value));
  const rowsRef = useRef(rows);
  rowsRef.current = rows;
  const valueKey = JSON.stringify(value);

  useEffect(() => {
    const rowsEnv = JSON.stringify(fromRows(rowsRef.current));
    if (valueKey !== rowsEnv) {
      setRows(toRows(value));
    }
  }, [valueKey, value]);

  function updateRow(index: number, patch: Partial<Row>) {
    setRows((prev) => {
      const next = prev.map((row, i) => (i === index ? { ...row, ...patch } : row));
      onChange(fromRows(next));
      return next;
    });
  }

  function addRow() {
    setRows((prev) => [...prev, { key: "", value: "" }]);
  }

  function removeRow(index: number) {
    setRows((prev) => {
      const next = prev.filter((_, i) => i !== index);
      const final = next.length ? next : [{ key: "", value: "" }];
      onChange(fromRows(final));
      return final;
    });
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
