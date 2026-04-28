import { useState, useEffect } from "react";

interface Props {
  value: Record<string, unknown>;
  onChange: (value: Record<string, unknown>) => void;
  readOnly?: boolean;
  error?: string;
}

export function JsonEditor({ value, onChange, readOnly = false, error }: Props) {
  const [text, setText] = useState(() => JSON.stringify(value, null, 2));
  const [parseError, setParseError] = useState<string | null>(null);

  useEffect(() => {
    setText(JSON.stringify(value, null, 2));
  }, [value]);

  function handleBlur() {
    try {
      const parsed = JSON.parse(text);
      if (typeof parsed !== "object" || Array.isArray(parsed) || parsed === null) {
        setParseError("Must be a JSON object");
        return;
      }
      setParseError(null);
      onChange(parsed as Record<string, unknown>);
    } catch {
      setParseError("Invalid JSON");
    }
  }

  const displayError = parseError ?? error;

  return (
    <div>
      <textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        onBlur={handleBlur}
        readOnly={readOnly}
        rows={8}
        spellCheck={false}
        className={`font-mono text-sm border rounded px-3 py-2 w-full focus:outline-none focus:ring-2 focus:ring-blue-500 resize-y ${
          readOnly ? "bg-gray-50 text-gray-600 cursor-default" : "bg-white"
        } ${displayError ? "border-red-400" : "border-gray-300"}`}
      />
      {displayError && (
        <p className="text-xs text-red-600 mt-1">{displayError}</p>
      )}
    </div>
  );
}
