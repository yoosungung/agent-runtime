import { useState } from "react";
import { FileDropZone } from "./FileDropZone";
import { useUploadSignature } from "../hooks/useSourceMeta";

interface Props {
  open: boolean;
  sourceMetaId: number;
  onClose: () => void;
  onSuccess: () => void;
}

export function SignatureUploadDialog({
  open,
  sourceMetaId,
  onClose,
  onSuccess,
}: Props) {
  const [sigFile, setSigFile] = useState<File | null>(null);
  const [error, setError] = useState<string | null>(null);
  const upload = useUploadSignature(sourceMetaId);

  if (!open) return null;

  async function handleSubmit() {
    if (!sigFile) {
      setError("Please select a .sig file");
      return;
    }
    setError(null);
    const fd = new FormData();
    fd.append("sig", sigFile);
    try {
      await upload.mutateAsync(fd);
      onSuccess();
      onClose();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Upload failed");
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div className="absolute inset-0 bg-black/50" onClick={onClose} />
      <div className="relative bg-white rounded-lg shadow-xl p-6 max-w-md w-full mx-4 z-10">
        <h2 className="text-lg font-semibold text-gray-900 mb-4">
          Upload Signature File
        </h2>
        <FileDropZone
          accept=".sig"
          maxMb={10}
          onFile={setSigFile}
          label="Select .sig signature file"
        />
        {error && <p className="text-sm text-red-600 mt-2">{error}</p>}
        <div className="flex justify-end gap-3 mt-6">
          <button
            onClick={onClose}
            className="px-4 py-2 rounded border border-gray-300 text-sm hover:bg-gray-50"
          >
            Cancel
          </button>
          <button
            onClick={handleSubmit}
            disabled={upload.isPending}
            className="bg-blue-600 text-white px-4 py-2 rounded hover:bg-blue-700 disabled:opacity-50 text-sm"
          >
            {upload.isPending ? "Uploading..." : "Upload"}
          </button>
        </div>
      </div>
    </div>
  );
}
