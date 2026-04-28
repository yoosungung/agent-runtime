import { useRef, useState } from "react";

interface Props {
  accept: string;
  maxMb?: number;
  onFile: (file: File) => void;
  label?: string;
}

export function FileDropZone({ accept, maxMb = 100, onFile, label }: Props) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [fileName, setFileName] = useState<string | null>(null);

  function validate(file: File): string | null {
    const ext = accept.replace("*", "");
    if (ext && !file.name.endsWith(ext) && accept !== "*") {
      const exts = accept.split(",").map((e) => e.trim());
      const ok = exts.some((e) => file.name.endsWith(e.replace("*", "")));
      if (!ok) return `File must be: ${accept}`;
    }
    if (file.size > maxMb * 1024 * 1024) {
      return `File must be under ${maxMb} MB (got ${(file.size / 1024 / 1024).toFixed(1)} MB)`;
    }
    return null;
  }

  function handleFile(file: File) {
    const err = validate(file);
    if (err) {
      setError(err);
      setFileName(null);
      return;
    }
    setError(null);
    setFileName(file.name);
    onFile(file);
  }

  return (
    <div>
      <div
        onClick={() => inputRef.current?.click()}
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragging(false);
          const file = e.dataTransfer.files[0];
          if (file) handleFile(file);
        }}
        className={`border-2 border-dashed rounded-lg p-6 text-center cursor-pointer transition-colors ${
          dragging
            ? "border-blue-400 bg-blue-50"
            : "border-gray-300 hover:border-gray-400 bg-white"
        }`}
      >
        <input
          ref={inputRef}
          type="file"
          accept={accept}
          className="hidden"
          onChange={(e) => {
            const file = e.target.files?.[0];
            if (file) handleFile(file);
          }}
        />
        {fileName ? (
          <div>
            <p className="text-sm font-medium text-gray-900">{fileName}</p>
            <p className="text-xs text-gray-500 mt-1">Click to change</p>
          </div>
        ) : (
          <div>
            <p className="text-sm text-gray-600">
              {label ?? "Drag & drop or click to select"}
            </p>
            <p className="text-xs text-gray-400 mt-1">
              {accept} · max {maxMb} MB
            </p>
          </div>
        )}
      </div>
      {error && <p className="text-xs text-red-600 mt-1">{error}</p>}
    </div>
  );
}
