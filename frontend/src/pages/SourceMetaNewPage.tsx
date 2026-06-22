import { useState } from "react";
import JSZip from "jszip";
import { useNavigate } from "react-router-dom";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { type z } from "zod";
import { sourceMetaCreateSchema } from "../lib/schemas";
import { getRuntimeKinds } from "../lib/enums";
import { sourceMetaDetailPath } from "../lib/sourceMetaPaths";
import { useCreateSourceMeta, useUploadBundle } from "../hooks/useSourceMeta";
import { JsonEditor } from "../components/JsonEditor";
import { FileDropZone } from "../components/FileDropZone";
import {
  FormActions,
  FormError,
  FormPageLayout,
  formPrimaryButtonClassName,
  formSecondaryButtonClassName,
} from "../components/FormPageLayout";
import {
  createSubmitLabel,
  createSubmitPendingLabel,
  newPageTitle,
  uploadSubmitLabel,
  uploadSubmitPendingLabel,
} from "../lib/uiLabels";

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
  const listPath = kind === "agent" ? "/bundle/agents" : "/bundle/mcp";
  const title = newPageTitle("bundle", kind);

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
    getValues,
    trigger,
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
      navigate(sourceMetaDetailPath(result));
    } catch (e: unknown) {
      setGlobalError(e instanceof Error ? e.message : "Failed to create");
    }
  }

  async function onSubmitZip() {
    if (!zipFile) {
      setGlobalError("Please select a ZIP file");
      return;
    }
    const valid = await trigger(["name", "version", "runtime_pool", "entrypoint"]);
    if (!valid) return;

    setGlobalError(null);
    const fd = new FormData();
    fd.append("file", zipFile);
    if (sigFile) fd.append("sig", sigFile);

    const { name, version, runtime_pool, entrypoint } = getValues();
    const meta = {
      kind,
      name,
      version,
      runtime_pool,
      entrypoint,
      config,
    };
    fd.append("meta", JSON.stringify(meta));

    try {
      const result = await uploadMut.mutateAsync(fd);
      navigate(sourceMetaDetailPath(result));
    } catch (e: unknown) {
      const status = (e as { status?: number })?.status;
      if (status === 413) setGlobalError("File too large");
      else if (status === 409) setGlobalError("Duplicate (kind, name, version)");
      else if (status === 400) setGlobalError(e instanceof Error ? e.message : "Invalid ZIP");
      else setGlobalError(e instanceof Error ? e.message : "Upload failed");
    }
  }

  return (
    <FormPageLayout title={title}>
        <div className="flex gap-4 border-b border-gray-200 mb-6 overflow-x-auto">
          <button
            type="button"
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
            type="button"
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

        {globalError && <FormError message={globalError} />}

        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (tab === "uri") {
              void handleSubmit(onSubmitUri)(e);
            } else {
              void onSubmitZip();
            }
          }}
          className="space-y-5"
        >
          <input type="hidden" {...register("kind")} value={kind} />

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <label
                htmlFor="source-meta-name"
                className="block text-sm font-medium text-gray-700 mb-1"
              >
                Name <span className="text-red-500">*</span>
              </label>
              <input
                id="source-meta-name"
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
              <label
                htmlFor="source-meta-version"
                className="block text-sm font-medium text-gray-700 mb-1"
              >
                Version <span className="text-red-500">*</span>
              </label>
              <input
                id="source-meta-version"
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
            <label
              htmlFor="source-meta-runtime-pool"
              className="block text-sm font-medium text-gray-700 mb-1"
            >
              Runtime Pool <span className="text-red-500">*</span>
            </label>
            <select
              id="source-meta-runtime-pool"
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
            <label
              htmlFor="source-meta-entrypoint"
              className="block text-sm font-medium text-gray-700 mb-1"
            >
              Entrypoint <span className="text-red-500">*</span>
            </label>
            <input
              id="source-meta-entrypoint"
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

          {tab === "uri" && (
            <>
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
            </>
          )}

          {tab === "zip" && (
            <>
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
            </>
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

          <FormActions>
            <button
              type="button"
              onClick={() => navigate(listPath)}
              className={formSecondaryButtonClassName}
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={
                tab === "uri"
                  ? isSubmitting || createMut.isPending
                  : uploadMut.isPending
              }
              className={formPrimaryButtonClassName}
            >
              {tab === "uri"
                ? isSubmitting || createMut.isPending
                  ? createSubmitPendingLabel(kind)
                  : createSubmitLabel(kind)
                : uploadMut.isPending
                  ? uploadSubmitPendingLabel(kind)
                  : uploadSubmitLabel(kind)}
            </button>
          </FormActions>
        </form>
    </FormPageLayout>
  );
}
