import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { PageHeader } from "../../components/PageHeader";
import {
  type CreateSourceInput,
  type SourceDriver,
  useCreatePipelineProject,
  useCreatePipelineSource,
  usePipelineProjects,
} from "../hooks/usePipeline";
import { usePipelineCredentials } from "../hooks/usePipelineCredentials";
import { parseGDriveFolderId } from "../lib/gdriveConfig";
import { MANUAL_DEFAULT_ALLOWED_EXTENSIONS } from "../lib/manualSourceDefaults";

const DRIVERS: { value: SourceDriver; label: string }[] = [
  { value: "sharepoint", label: "SharePoint" },
  { value: "gdrive", label: "Google Drive" },
  { value: "onedrive", label: "OneDrive" },
  { value: "manual", label: "Manual upload" },
];

function defaultConfig(driver: SourceDriver): Record<string, unknown> {
  if (driver === "sharepoint") {
    return { site: "", drive: "Documents", folder: "" };
  }
  if (driver === "gdrive") {
    return { folder_id: "", folder_path: "" };
  }
  if (driver === "manual") {
    return { allowed_extensions: MANUAL_DEFAULT_ALLOWED_EXTENSIONS, max_file_mb: "100" };
  }
  return { folder: "" };
}

function defaultSourceId(name: string, driver: SourceDriver): string {
  const slug = name.trim().toLowerCase().replace(/\s+/g, "-");
  if (!slug) return "";
  return `${driver}:${slug}`;
}

export function PipelineSourceNewPage() {
  const navigate = useNavigate();
  const { projectId: routeProjectId } = useParams<{ projectId: string }>();
  const createMut = useCreatePipelineSource();
  const createProjectMut = useCreatePipelineProject();
  const { data: projectData, isLoading: projectsLoading } = usePipelineProjects();
  const { data: credData } = usePipelineCredentials();
  const projects = projectData?.items ?? [];
  const [projectId, setProjectId] = useState("");
  const [driver, setDriver] = useState<SourceDriver>("sharepoint");
  const [credentialId, setCredentialId] = useState("");
  const [name, setName] = useState("");
  const [sourceId, setSourceId] = useState("");
  const [config, setConfig] = useState<Record<string, string>>(() =>
    Object.fromEntries(
      Object.entries(defaultConfig("sharepoint")).map(([k, v]) => [k, String(v)]),
    ),
  );
  const [scheduleCron, setScheduleCron] = useState("");
  const [error, setError] = useState<string | null>(null);

  const effectiveProjectId = routeProjectId || projectId || projects[0]?.id || "";

  function handleDriverChange(next: SourceDriver) {
    setDriver(next);
    setCredentialId("");
    setConfig(
      Object.fromEntries(
        Object.entries(defaultConfig(next)).map(([k, v]) => [k, String(v)]),
      ),
    );
    if (name.trim()) {
      setSourceId(defaultSourceId(name, next));
    }
  }

  function handleNameChange(value: string) {
    setName(value);
    if (!sourceId || sourceId === defaultSourceId(name, driver)) {
      setSourceId(defaultSourceId(value, driver));
    }
  }

  function buildGDriveConfig(raw: Record<string, string>): Record<string, unknown> {
    const folderId = parseGDriveFolderId(raw.folder_id ?? "");
    const folderPath = (raw.folder_path ?? "").trim();
    const out: Record<string, unknown> = {};
    if (folderId) out.folder_id = folderId;
    if (folderPath) out.folder_path = folderPath;
    return out;
  }

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    const resolvedConfig =
      driver === "gdrive"
        ? buildGDriveConfig(config)
        : driver === "manual"
          ? {
              allowed_extensions: (config.allowed_extensions ?? "").trim(),
              max_file_mb: Number(config.max_file_mb || 100),
            }
          : { ...config };
    const body: CreateSourceInput = {
      project_id: effectiveProjectId,
      name: name.trim(),
      driver,
      source_id: sourceId.trim(),
      config: resolvedConfig,
      credential_id: credentialId || undefined,
      schedule_cron: driver !== "manual" && scheduleCron.trim() ? scheduleCron.trim() : undefined,
    };
    try {
      const created = await createMut.mutateAsync(body);
      const pid = routeProjectId ?? effectiveProjectId;
      navigate(`/pipeline/projects/${pid}/sources/${created.id}`);
    } catch (err: unknown) {
      const status = (err as { status?: number })?.status;
      if (status === 409) {
        setError("Source name already exists for this tenant.");
      } else if (status === 404) {
        setError("Selected project was not found. Refresh and try again.");
      } else {
        setError(err instanceof Error ? err.message : "Failed to create source");
      }
    }
  }

  async function onCreateDefaultProject() {
    setError(null);
    try {
      const created = await createProjectMut.mutateAsync({
        name: "Default",
        slug: "default",
      });
      setProjectId(created.id);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to create project");
    }
  }

  return (
    <div>
      <PageHeader title="New Pipeline Source" />

      <p className="mb-4 text-sm text-gray-600">
        {driver === "manual" ? (
          <>
            Manual source는 UI에서 raw 파일을 직접 업로드합니다. OAuth credential이 필요 없습니다.
          </>
        ) : (
          <>
            먼저{" "}
            <a href="/pipeline/credentials" className="text-blue-600 hover:underline">
              Credentials
            </a>
            에서 OAuth 계정을 연결한 뒤, 아래에서 해당 credential을 선택하세요.
          </>
        )}
      </p>

      <div className="bg-white shadow rounded-lg p-6 max-w-xl">
        {error && (
          <div className="mb-4 bg-red-50 border border-red-200 rounded px-4 py-3 text-sm text-red-700">
            {error}
          </div>
        )}

        <form onSubmit={onSubmit} className="space-y-4">
          {!routeProjectId && (
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Project <span className="text-red-500">*</span>
            </label>
            {projectsLoading ? (
              <p className="text-sm text-gray-500">Loading projects…</p>
            ) : projects.length === 0 ? (
              <div className="space-y-2">
                <p className="text-sm text-gray-600">
                  Project가 없습니다. Default project를 만든 뒤 Source를 등록하세요.
                </p>
                <button
                  type="button"
                  onClick={onCreateDefaultProject}
                  disabled={createProjectMut.isPending}
                  className="text-sm bg-gray-100 hover:bg-gray-200 text-gray-800 px-3 py-1.5 rounded disabled:opacity-50"
                >
                  {createProjectMut.isPending ? "Creating…" : "Create default project"}
                </button>
              </div>
            ) : (
              <>
                <select
                  value={effectiveProjectId}
                  onChange={(e) => setProjectId(e.target.value)}
                  className="border border-gray-300 rounded px-3 py-2 w-full"
                  required
                >
                  {projects.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.name} ({p.slug})
                    </option>
                  ))}
                </select>
                <p className="mt-1 text-xs text-gray-500">
                  <a href="/pipeline" className="text-blue-600 hover:underline">
                    Manage projects
                  </a>
                </p>
              </>
            )}
          </div>
          )}

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Name</label>
            <input
              value={name}
              onChange={(e) => handleNameChange(e.target.value)}
              className="border border-gray-300 rounded px-3 py-2 w-full"
              required
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Driver</label>
            <select
              value={driver}
              onChange={(e) => handleDriverChange(e.target.value as SourceDriver)}
              className="border border-gray-300 rounded px-3 py-2 w-full"
            >
              {DRIVERS.map((d) => (
                <option key={d.value} value={d.value}>
                  {d.label}
                </option>
              ))}
            </select>
          </div>

          {driver !== "manual" && (
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Credential <span className="text-red-500">*</span>
              </label>
              <select
                value={credentialId}
                onChange={(e) => setCredentialId(e.target.value)}
                className="border border-gray-300 rounded px-3 py-2 w-full"
                required
              >
                <option value="">Select connected credential…</option>
                {(credData?.items ?? [])
                  .filter((c) => c.driver === driver && c.oauth_status === "connected")
                  .map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.label}
                    </option>
                  ))}
              </select>
              <p className="mt-1 text-xs text-gray-500">
                driver와 일치하고 <code className="bg-gray-100 px-0.5 rounded">connected</code>{" "}
                상태인 credential만 표시됩니다.
              </p>
            </div>
          )}

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Source ID</label>
            <input
              value={sourceId}
              onChange={(e) => setSourceId(e.target.value)}
              className="border border-gray-300 rounded px-3 py-2 w-full font-mono text-sm"
              required
            />
          </div>

          {driver === "sharepoint" && (
            <>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Site</label>
                <input
                  value={config.site ?? ""}
                  onChange={(e) => setConfig({ ...config, site: e.target.value })}
                  placeholder="host:/sites/kms"
                  className="border border-gray-300 rounded px-3 py-2 w-full"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Drive</label>
                <input
                  value={config.drive ?? ""}
                  onChange={(e) => setConfig({ ...config, drive: e.target.value })}
                  className="border border-gray-300 rounded px-3 py-2 w-full"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Folder</label>
                <input
                  value={config.folder ?? ""}
                  onChange={(e) => setConfig({ ...config, folder: e.target.value })}
                  className="border border-gray-300 rounded px-3 py-2 w-full"
                />
              </div>
            </>
          )}

          {driver === "gdrive" && (
            <>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Folder ID or URL
                </label>
                <input
                  value={config.folder_id ?? ""}
                  onChange={(e) => setConfig({ ...config, folder_id: e.target.value })}
                  onBlur={(e) =>
                    setConfig({
                      ...config,
                      folder_id: parseGDriveFolderId(e.target.value),
                    })
                  }
                  placeholder="https://drive.google.com/drive/folders/…"
                  className="border border-gray-300 rounded px-3 py-2 w-full font-mono text-sm"
                />
                <p className="mt-1 text-xs text-gray-500">
                  Drive에서 복사한 폴더 URL 또는 ID를 붙여넣으세요. 예:{" "}
                  <code className="bg-gray-100 px-0.5 rounded break-all">
                    1UTtmbCL8OxKoCED23PlTXan6N0JYcjnu
                  </code>
                  . URL이 있으면 <strong>Folder path</strong>보다 우선합니다.
                </p>
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Folder path <span className="text-gray-400 font-normal">(선택)</span>
                </label>
                <input
                  value={config.folder_path ?? ""}
                  onChange={(e) => setConfig({ ...config, folder_path: e.target.value })}
                  placeholder="Reports/2024"
                  className="border border-gray-300 rounded px-3 py-2 w-full"
                />
                <p className="mt-1 text-xs text-gray-500">
                  URL/ID 대신 <strong>내 드라이브</strong> 루트부터 폴더 이름 경로로 지정할 때만
                  사용합니다 (<code className="bg-gray-100 px-0.5 rounded">회사규정/2024</code>).
                  비우면 내 드라이브 전체입니다.
                </p>
              </div>
            </>
          )}

          {driver === "manual" && (
            <>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Allowed extensions
                </label>
                <input
                  value={config.allowed_extensions ?? ""}
                  onChange={(e) =>
                    setConfig({ ...config, allowed_extensions: e.target.value })
                  }
                  placeholder={MANUAL_DEFAULT_ALLOWED_EXTENSIONS}
                  className="border border-gray-300 rounded px-3 py-2 w-full font-mono text-sm"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Max file size (MB)
                </label>
                <input
                  type="number"
                  min={1}
                  value={config.max_file_mb ?? "100"}
                  onChange={(e) => setConfig({ ...config, max_file_mb: e.target.value })}
                  className="border border-gray-300 rounded px-3 py-2 w-full"
                />
              </div>
            </>
          )}

          {driver === "onedrive" && (
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Folder</label>
              <input
                value={config.folder ?? ""}
                onChange={(e) => setConfig({ ...config, folder: e.target.value })}
                className="border border-gray-300 rounded px-3 py-2 w-full"
              />
            </div>
          )}

          {driver !== "manual" && (
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Schedule cron <span className="text-gray-400 font-normal">(선택, UTC)</span>
              </label>
              <input
                value={scheduleCron}
                onChange={(e) => setScheduleCron(e.target.value)}
                placeholder="0 2 * * *"
                className="border border-gray-300 rounded px-3 py-2 w-full font-mono text-sm"
              />
              <p className="mt-1 text-xs text-gray-500">
                설정 시 Argo CronWorkflow가 주기적으로 collect+ingest를 실행합니다.
              </p>
            </div>
          )}

          <div className="flex gap-2 pt-2">
            <button
              type="submit"
              disabled={createMut.isPending || !effectiveProjectId}
              className="bg-blue-600 hover:bg-blue-700 text-white px-4 py-2 rounded text-sm disabled:opacity-50"
            >
              {createMut.isPending ? "Creating…" : "Create"}
            </button>
            <button
              type="button"
              onClick={() =>
                navigate(
                  routeProjectId
                    ? `/pipeline/projects/${routeProjectId}/sources`
                    : "/pipeline",
                )
              }
              className="text-sm text-gray-600 hover:underline px-2"
            >
              Cancel
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
