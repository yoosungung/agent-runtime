import { useRef, useState } from "react";
import {
  collectDroppedFiles,
  fileMatchesAccept,
  filterAcceptedFiles,
  type SkippedFile,
  validateFileSize,
} from "../lib/fileDropHelpers";

interface Props {
  accept: string;
  maxMb?: number;
  onFile?: (file: File) => void;
  onFiles?: (files: File[]) => void;
  multiple?: boolean;
  allowDirectories?: boolean;
  label?: string;
}

export function FileDropZone({
  accept,
  maxMb = 100,
  onFile,
  onFiles,
  multiple = false,
  allowDirectories = false,
  label,
}: Props) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [skipped, setSkipped] = useState<SkippedFile[]>([]);
  const [showSkipped, setShowSkipped] = useState(false);
  const [fileName, setFileName] = useState<string | null>(null);

  function validateSingle(file: File): string | null {
    if (!fileMatchesAccept(file.name, accept)) {
      return `File must be: ${accept}`;
    }
    return validateFileSize(file, maxMb);
  }

  function processMultiple(files: File[]) {
    const { accepted, rejected } = filterAcceptedFiles(files, accept, maxMb);
    setSkipped(rejected);
    setShowSkipped(false);

    if (accepted.length === 0) {
      setError(
        rejected.length > 0
          ? `No matching files (${accept}). ${rejected.length} skipped — click below to view.`
          : `File must be: ${accept}`,
      );
      setFileName(null);
      if (rejected.length > 0) setShowSkipped(true);
      return;
    }

    setError(null);
    setFileName(
      accepted.length === 1 ? accepted[0].name : `${accepted.length} files selected`,
    );
    onFiles?.(accepted);
  }

  function handleFiles(fileList: FileList | File[]) {
    const arr = Array.from(fileList);
    if (multiple) {
      processMultiple(arr);
      return;
    }
    if (arr[0]) handleFile(arr[0]);
  }

  function handleFile(file: File) {
    setSkipped([]);
    setShowSkipped(false);
    const err = validateSingle(file);
    if (err) {
      setError(err);
      setFileName(null);
      return;
    }
    setError(null);
    setFileName(file.name);
    onFile?.(file);
  }

  async function handleDrop(e: React.DragEvent) {
    e.preventDefault();
    setDragging(false);
    const files = allowDirectories
      ? await collectDroppedFiles(e.dataTransfer, true)
      : Array.from(e.dataTransfer.files);
    if (files.length) handleFiles(files);
  }

  return (
    <div>
      <div
        onClick={() => inputRef.current?.click()}
        onDragOver={(ev) => {
          ev.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={handleDrop}
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
          multiple={multiple}
          {...(allowDirectories && multiple
            ? ({ webkitdirectory: "", directory: "" } as React.InputHTMLAttributes<HTMLInputElement>)
            : {})}
          className="hidden"
          onChange={(e) => {
            if (e.target.files?.length) handleFiles(e.target.files);
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
      {skipped.length > 0 && (
        <div className="mt-1">
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              setShowSkipped((v) => !v);
            }}
            className="text-xs text-amber-700 hover:text-amber-900 underline text-left"
          >
            {skipped.length} file(s) skipped (extension or size).
            {showSkipped ? " Click to hide." : " Click to show."}
          </button>
          {showSkipped && (
            <ul className="mt-1 max-h-48 overflow-y-auto rounded border border-amber-200 bg-amber-50 px-2 py-1 text-xs text-amber-900">
              {skipped.map((item) => (
                <li key={item.displayName} className="py-0.5 border-b border-amber-100 last:border-0">
                  <span className="font-mono break-all">{item.displayName}</span>
                  <span className="text-amber-700"> — {item.reason}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
