import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { PageHeader } from "../components/PageHeader";
import { VfsBreadcrumbs } from "../components/VfsBreadcrumbs";
import {
  usePatchVfsUserFile,
  usePatchVfsWikiFile,
  useVfsUserEntries,
  useVfsUserFile,
  useVfsWikiEntries,
  useVfsWikiFile,
  vfsErrorMessage,
  type VfsEntry,
} from "../hooks/useVfs";
import { formatVfsSize, normalizeVfsDir } from "../lib/vfsPaths";

type VfsScope = "user" | "wiki";

function useScopedVfs(scope: VfsScope, id: string, dirPath: string, selectedPath: string | null) {
  const userEntries = useVfsUserEntries(id, dirPath);
  const wikiEntries = useVfsWikiEntries(id, dirPath);
  const userFile = useVfsUserFile(id, selectedPath);
  const wikiFile = useVfsWikiFile(id, selectedPath);
  const patchUser = usePatchVfsUserFile(id);
  const patchWiki = usePatchVfsWikiFile(id);
  if (scope === "user") {
    return {
      entries: userEntries,
      file: userFile,
      patch: patchUser,
    };
  }
  return {
    entries: wikiEntries,
    file: wikiFile,
    patch: patchWiki,
  };
}

export function VfsScopedBrowserPage({ scope }: { scope: VfsScope }) {
  const { id = "" } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [dirPath, setDirPath] = useState("/");
  const [selectedPath, setSelectedPath] = useState<string | null>(null);
  const [editorContent, setEditorContent] = useState("");
  const [editorDirty, setEditorDirty] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  const { entries, file, patch } = useScopedVfs(scope, id, dirPath, selectedPath);
  const items = entries.data?.items ?? [];

  useEffect(() => {
    if (file.data && !editorDirty) {
      setEditorContent(file.data.content);
    }
  }, [file.data, editorDirty]);

  function openDir(entry: VfsEntry) {
    if (!entry.is_dir) return;
    const next = entry.path.endsWith("/") ? entry.path : `${entry.path}/`;
    setDirPath(normalizeVfsDir(next));
    setSelectedPath(null);
    setEditorDirty(false);
  }

  function openFile(entry: VfsEntry) {
    if (entry.is_dir) return;
    setSelectedPath(entry.path);
    setEditorDirty(false);
  }

  async function handleSave() {
    if (!selectedPath) return;
    setActionError(null);
    try {
      await patch.mutateAsync({ path: selectedPath, content: editorContent });
      setEditorDirty(false);
    } catch (err) {
      setActionError(vfsErrorMessage(err));
    }
  }

  const title = scope === "user" ? `VFS — User ${id}` : `VFS — Wiki ${id}`;
  const home = scope === "user" ? "/vfs/user" : "/vfs/wiki";

  return (
    <div>
      <PageHeader title={title}>
        <button type="button" className="text-sm text-blue-600" onClick={() => navigate(home)}>
          ← Back
        </button>
      </PageHeader>
      <VfsBreadcrumbs path={dirPath} onNavigate={setDirPath} />
      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <div className="rounded border border-gray-200">
          <ul className="divide-y text-sm">
            {entries.isLoading && <li className="px-3 py-2 text-gray-500">Loading…</li>}
            {items.map((entry) => (
              <li
                key={entry.path}
                className="flex cursor-pointer items-center justify-between px-3 py-2 hover:bg-gray-50"
                onClick={() => (entry.is_dir ? openDir(entry) : openFile(entry))}
              >
                <span>{entry.is_dir ? `${entry.name}/` : entry.name}</span>
                <span className="text-xs text-gray-500">{formatVfsSize(entry.size)}</span>
              </li>
            ))}
            {dirPath !== "/" && (
              <li
                className="cursor-pointer px-3 py-2 text-blue-600 hover:bg-gray-50"
                onClick={() => {
                  const parent =
                    dirPath.replace(/\/$/, "").split("/").slice(0, -1).join("/") || "/";
                  setDirPath(parent === "" ? "/" : `${parent}/`);
                  setSelectedPath(null);
                }}
              >
                ..
              </li>
            )}
          </ul>
        </div>
        <div className="rounded border border-gray-200 p-3">
          {selectedPath ? (
            <>
              <div className="mb-2 font-mono text-xs text-gray-600">{selectedPath}</div>
              <textarea
                className="h-64 w-full rounded border p-2 font-mono text-sm"
                value={editorContent}
                onChange={(e) => {
                  setEditorContent(e.target.value);
                  setEditorDirty(true);
                }}
              />
              <button
                type="button"
                className="mt-2 rounded bg-blue-600 px-3 py-1 text-sm text-white disabled:opacity-50"
                disabled={!editorDirty || patch.isPending}
                onClick={handleSave}
              >
                Save
              </button>
            </>
          ) : (
            <p className="text-sm text-gray-500">Select a file to edit</p>
          )}
          {actionError && <p className="mt-2 text-sm text-red-600">{actionError}</p>}
        </div>
      </div>
    </div>
  );
}
