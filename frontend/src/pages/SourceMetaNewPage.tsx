import { useState } from "react";
import JSZip from "jszip";
import { useNavigate } from "react-router-dom";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { type z } from "zod";
import { sourceMetaCreateSchema } from "../lib/schemas";
import { getRuntimeKinds } from "../lib/enums";
import { useCreateSourceMeta, useUploadBundle } from "../hooks/useSourceMeta";
import { JsonEditor } from "../components/JsonEditor";
import { FileDropZone } from "../components/FileDropZone";

const DECOMPRESSED_WARN_MB = 500;

interface ZipStats {
  compressedMb: number;
  decompressedMb: number;
  fileCount: number;
}

async function inspectZip(file: File): Promise<ZipStats> {
  const zip = await JSZip.loadAsync(file);
  let decompressedBytes = 0;
  let fileCount = 0;
  zip.forEach((_path, entry) => {
    if (!entry.dir) {
      fileCount++;
      // _data is an internal property with uncompressedSize
      const data = (entry as unknown as { _data?: { uncompressedSize?: number } })._data;
      decompressedBytes += data?.uncompressedSize ?? 0;
    }
  });
  return {
    compressedMb: file.size / 1024 / 1024,
    decompressedMb: decompressedBytes / 1024 / 1024,
    fileCount,
  };
}

interface Props {
  kind: "agent" | "mcp";
}

type FormValues = z.infer<typeof sourceMetaCreateSchema>;

export function SourceMetaNewPage({ kind }: Props) {
  const navigate = useNavigate();
  const basePath = kind === "agent" ? "/agents" : "/mcp-servers";
  const title = kind === "agent" ? "New Agent" : "New MCP Server";

  const [tab, setTab] = useState<"uri" | "zip">("uri");
  const [config, setConfig] = useState<Record<string, unknown>>({});
  const [configError, setConfigError] = useState<string | undefined>();
  const [globalError, setGlobalError] = useState<string | null>(null);

  // ZIP upload state
  const [zipFile, setZipFile] = useState<File | null>(null);
  const [sigFile, setSigFile] = useState<File | null>(null);
  const [zipStats, setZipStats] = useState<ZipStats | null>(null);
  const [zipStatsError, setZipStatsError] = useState<string | null>(null);

  const createMut = useCreateSourceMeta();
  const uploadMut = useUploadBundle();

  async function handleZipFile(file: File) {
    setZipFile(file);
    setZipStats(null);
    setZipStatsError(null);
    try {
      const stats = await inspectZip(file);
      setZipStats(stats);
    } catch {
      setZipStatsError("ZIP 파일 분석 실패 — 손상된 파일일 수 있습니다.");
    }
  }

  const runtimeKinds = getRuntimeKinds(kind);

  const {
    register,
    handleSubmit,
    watch,
    formState: { errors, isSubmitting },
  } = useForm<FormValues>({
    resolver: zodResolver(sourceMetaCreateSchema),
    defaultValues: {
      kind,
      config: {},
    },
  });

  const bundleUri = watch("bundle_uri");
  const requiresChecksum =
    bundleUri?.startsWith("s3://") || bundleUri?.startsWith("oci://");

  async function onSubmitUri(values: FormValues) {
    setGlobalError(null);
    try {
      const payload = { ...values, config };
      if (!requiresChecksum) delete payload.checksum;
      const result = await createMut.mutateAsync(payload);
      navigate(`${basePath}/${result.id}`);
    } catch (e: unknown) {
      setGlobalError(e instanceof Error ? e.message : "Failed to create");
    }
  }

  async function onSubmitZip() {
    if (!zipFile) {
      setGlobalError("Please select a ZIP file");
      return;
    }
    setGlobalError(null);
    const fd = new FormData();
    fd.append("file", zipFile);
    if (sigFile) fd.append("sig", sigFile);
    // Get current form values
    const nameEl = document.getElementById("zip-name") as HTMLInputElement;
    const versionEl = document.getElementById(
      "zip-version",
    ) as HTMLInputElement;
    const runtimePoolEl = document.getElementById(
      "zip-runtime-pool",
    ) as HTMLSelectElement;
    const entrypointEl = document.getElementById(
      "zip-entrypoint",
    ) as HTMLInputElement;

    const meta = {
      kind,
      name: nameEl?.value,
      version: versionEl?.value,
      runtime_pool: runtimePoolEl?.value,
      entrypoint: entrypointEl?.value,
      config,
    };
    fd.append("meta", JSON.stringify(meta));

    try {
      const result = await uploadMut.mutateAsync(fd);
      navigate(`${basePath}/${result.id}`);
    } catch (e: unknown) {
      const status = (e as { status?: number })?.status;
      if (status === 413) setGlobalError("File too large");
      else if (status === 409) setGlobalError("Duplicate (kind, name, version)");
      else if (status === 400) setGlobalError(e instanceof Error ? e.message : "Invalid ZIP");
      else setGlobalError(e instanceof Error ? e.message : "Upload failed");
    }
  }

  return (
    <div>
      <h1 className="text-2xl font-bold text-gray-900 mb-6">{title}</h1>

      <div className="bg-white shadow rounded-lg p-6">
        {/* Tabs */}
        <div className="flex gap-4 border-b border-gray-200 mb-6">
          <button
            onClick={() => setTab("uri")}
            className={`pb-3 text-sm font-medium border-b-2 transition-colors ${
              tab === "uri"
                ? "border-blue-600 text-blue-600"
                : "border-transparent text-gray-500 hover:text-gray-700"
            }`}
          >
            External URI
          </button>
          <button
            onClick={() => setTab("zip")}
            className={`pb-3 text-sm font-medium border-b-2 transition-colors ${
              tab === "zip"
                ? "border-blue-600 text-blue-600"
                : "border-transparent text-gray-500 hover:text-gray-700"
            }`}
          >
            ZIP Upload
          </button>
        </div>

        {globalError && (
          <div className="mb-4 bg-red-50 border border-red-200 rounded px-4 py-3 text-sm text-red-700">
            {globalError}
          </div>
        )}

        {tab === "uri" && (
          <form onSubmit={handleSubmit(onSubmitUri)} className="space-y-5">
            <input type="hidden" {...register("kind")} value={kind} />

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Name <span className="text-red-500">*</span>
                </label>
                <input
                  {...register("name")}
                  className="border border-gray-300 rounded px-3 py-2 w-full focus:outline-none focus:ring-2 focus:ring-blue-500"
                  placeholder="my-agent"
                />
                {errors.name && (
                  <p className="text-xs text-red-600 mt-1">
                    {errors.name.message}
                  </p>
                )}
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Version <span className="text-red-500">*</span>
                </label>
                <input
                  {...register("version")}
                  className="border border-gray-300 rounded px-3 py-2 w-full focus:outline-none focus:ring-2 focus:ring-blue-500"
                  placeholder="1.0.0"
                />
                {errors.version && (
                  <p className="text-xs text-red-600 mt-1">
                    {errors.version.message}
                  </p>
                )}
              </div>
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Runtime Pool <span className="text-red-500">*</span>
              </label>
              <select
                {...register("runtime_pool")}
                className="border border-gray-300 rounded px-3 py-2 w-full focus:outline-none focus:ring-2 focus:ring-blue-500"
              >
                <option value="">Select runtime pool...</option>
                {runtimeKinds.map((rk) => (
                  <option key={rk} value={rk}>
                    {rk}
                  </option>
                ))}
              </select>
              {errors.runtime_pool && (
                <p className="text-xs text-red-600 mt-1">
                  {errors.runtime_pool.message}
                </p>
              )}
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Entrypoint <span className="text-red-500">*</span>
              </label>
              <input
                {...register("entrypoint")}
                className="border border-gray-300 rounded px-3 py-2 w-full focus:outline-none focus:ring-2 focus:ring-blue-500"
                placeholder="module.path:factory"
              />
              {errors.entrypoint && (
                <p className="text-xs text-red-600 mt-1">
                  {errors.entrypoint.message}
                </p>
              )}
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Bundle URI
              </label>
              <input
                {...register("bundle_uri")}
                className="border border-gray-300 rounded px-3 py-2 w-full focus:outline-none focus:ring-2 focus:ring-blue-500"
                placeholder="s3://bucket/path/bundle.zip"
              />
              {errors.bundle_uri && (
                <p className="text-xs text-red-600 mt-1">
                  {errors.bundle_uri.message}
                </p>
              )}
            </div>

            {requiresChecksum && (
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Checksum <span className="text-red-500">*</span>{" "}
                  <span className="text-xs text-gray-400">
                    (required for s3/oci)
                  </span>
                </label>
                <input
                  {...register("checksum")}
                  className="border border-gray-300 rounded px-3 py-2 w-full focus:outline-none focus:ring-2 focus:ring-blue-500 font-mono"
                  placeholder="sha256:abc123..."
                />
                {errors.checksum && (
                  <p className="text-xs text-red-600 mt-1">
                    {errors.checksum.message}
                  </p>
                )}
              </div>
            )}

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Config (JSON)
              </label>
              <JsonEditor
                value={config}
                onChange={(v) => {
                  setConfig(v);
                  setConfigError(undefined);
                }}
                error={configError}
              />
            </div>

            <div className="flex gap-3 pt-2">
              <button
                type="submit"
                disabled={isSubmitting || createMut.isPending}
                className="bg-blue-600 text-white px-4 py-2 rounded hover:bg-blue-700 disabled:opacity-50"
              >
                {isSubmitting || createMut.isPending ? "Creating..." : "Create"}
              </button>
              <button
                type="button"
                onClick={() => navigate(basePath)}
                className="px-4 py-2 rounded border border-gray-300 hover:bg-gray-50"
              >
                Cancel
              </button>
            </div>
          </form>
        )}

        {tab === "zip" && (
          <div className="space-y-5">
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Name <span className="text-red-500">*</span>
                </label>
                <input
                  id="zip-name"
                  className="border border-gray-300 rounded px-3 py-2 w-full focus:outline-none focus:ring-2 focus:ring-blue-500"
                  placeholder="my-agent"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Version <span className="text-red-500">*</span>
                </label>
                <input
                  id="zip-version"
                  className="border border-gray-300 rounded px-3 py-2 w-full focus:outline-none focus:ring-2 focus:ring-blue-500"
                  placeholder="1.0.0"
                />
              </div>
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Runtime Pool <span className="text-red-500">*</span>
              </label>
              <select
                id="zip-runtime-pool"
                className="border border-gray-300 rounded px-3 py-2 w-full focus:outline-none focus:ring-2 focus:ring-blue-500"
              >
                <option value="">Select runtime pool...</option>
                {runtimeKinds.map((rk) => (
                  <option key={rk} value={rk}>
                    {rk}
                  </option>
                ))}
              </select>
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Entrypoint <span className="text-red-500">*</span>
              </label>
              <input
                id="zip-entrypoint"
                className="border border-gray-300 rounded px-3 py-2 w-full focus:outline-none focus:ring-2 focus:ring-blue-500"
                placeholder="module.path:factory"
              />
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Bundle ZIP <span className="text-red-500">*</span>
              </label>
              <FileDropZone
                accept=".zip"
                maxMb={100}
                onFile={handleZipFile}
                label="Drag & drop your .zip bundle"
              />
              {zipStatsError && (
                <p className="text-xs text-red-600 mt-1">{zipStatsError}</p>
              )}
              {zipStats && (
                <div className={`mt-2 rounded px-3 py-2 text-xs ${
                  zipStats.decompressedMb > DECOMPRESSED_WARN_MB
                    ? "bg-amber-50 border border-amber-200 text-amber-800"
                    : "bg-gray-50 border border-gray-200 text-gray-600"
                }`}>
                  <span className="font-medium">ZIP 분석:</span>{" "}
                  {zipStats.fileCount}개 파일 · 압축: {zipStats.compressedMb.toFixed(1)} MB · 압축 해제 추정: {zipStats.decompressedMb.toFixed(1)} MB
                  {zipStats.decompressedMb > DECOMPRESSED_WARN_MB && (
                    <span className="ml-2 font-semibold">
                      ⚠ {DECOMPRESSED_WARN_MB} MB 초과 — 디스크 용량을 확인하세요.
                    </span>
                  )}
                </div>
              )}
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Signature File{" "}
                <span className="text-xs text-gray-400">(optional)</span>
              </label>
              <FileDropZone
                accept=".sig"
                maxMb={10}
                onFile={setSigFile}
                label="Drag & drop .sig file (optional)"
              />
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Config (JSON)
              </label>
              <JsonEditor
                value={config}
                onChange={(v) => {
                  setConfig(v);
                  setConfigError(undefined);
                }}
                error={configError}
              />
            </div>

            <div className="flex gap-3 pt-2">
              <button
                type="button"
                onClick={onSubmitZip}
                disabled={uploadMut.isPending}
                className="bg-blue-600 text-white px-4 py-2 rounded hover:bg-blue-700 disabled:opacity-50"
              >
                {uploadMut.isPending ? "Uploading..." : "Upload & Create"}
              </button>
              <button
                type="button"
                onClick={() => navigate(basePath)}
                className="px-4 py-2 rounded border border-gray-300 hover:bg-gray-50"
              >
                Cancel
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
