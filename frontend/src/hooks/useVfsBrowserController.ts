import { useEffect, useMemo, useRef, useState } from "react";
import type { UseMutationResult } from "@tanstack/react-query";
import { joinVfsPath, normalizeVfsDir } from "../lib/vfsPaths";
import { vfsErrorMessage, type VfsEntry, type VfsFile } from "./useVfs";

type FileMutation = UseMutationResult<
  VfsFile,
  Error,
  { path: string; content: string },
  unknown
>;
type FolderMutation = UseMutationResult<
  VfsEntry,
  Error,
  { parent_path: string; name: string },
  unknown
>;
type DeleteMutation = UseMutationResult<void, Error, string, unknown>;

export function useVfsBrowserController(mutations: {
  createFile: FileMutation;
  patchFile: FileMutation;
  deletePath: DeleteMutation;
  createFolder: FolderMutation;
}) {
  const { createFile, patchFile, deletePath, createFolder } = mutations;
  const [dirPath, setDirPath] = useState("/");
  const [selectedPath, setSelectedPath] = useState<string | null>(null);
  const [editorContent, setEditorContent] = useState("");
  const [editorDirty, setEditorDirty] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [showFolderModal, setShowFolderModal] = useState(false);
  const [showNewFileModal, setShowNewFileModal] = useState(false);
  const [folderName, setFolderName] = useState("");
  const [newFileName, setNewFileName] = useState("");
  const [deleteTarget, setDeleteTarget] = useState<VfsEntry | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  function resetEditor() {
    setSelectedPath(null);
    setEditorContent("");
    setEditorDirty(false);
    setActionError(null);
  }

  function navigateDir(path: string) {
    setDirPath(normalizeVfsDir(path));
    resetEditor();
  }

  function openDir(entry: VfsEntry) {
    if (!entry.is_dir) return;
    const next = entry.path.endsWith("/") ? entry.path : `${entry.path}/`;
    navigateDir(next);
  }

  function openFile(entry: VfsEntry) {
    if (entry.is_dir) return;
    setSelectedPath(entry.path);
    setEditorDirty(false);
    setActionError(null);
  }

  async function handleSave() {
    if (!selectedPath) return;
    setActionError(null);
    try {
      await patchFile.mutateAsync({ path: selectedPath, content: editorContent });
      setEditorDirty(false);
    } catch (err) {
      setActionError(vfsErrorMessage(err));
    }
  }

  async function handleCreateFolder(e: React.FormEvent) {
    e.preventDefault();
    setActionError(null);
    try {
      await createFolder.mutateAsync({
        parent_path: dirPath,
        name: folderName.trim(),
      });
      setFolderName("");
      setShowFolderModal(false);
    } catch (err) {
      setActionError(vfsErrorMessage(err));
    }
  }

  async function handleCreateFile(e: React.FormEvent) {
    e.preventDefault();
    const fileName = newFileName.trim();
    if (!fileName) return;
    const path = joinVfsPath(dirPath === "/" ? "/" : dirPath.replace(/\/$/, ""), fileName);
    setActionError(null);
    try {
      const created = await createFile.mutateAsync({ path, content: "" });
      setNewFileName("");
      setShowNewFileModal(false);
      setSelectedPath(created.path);
      setEditorContent("");
      setEditorDirty(false);
    } catch (err) {
      setActionError(vfsErrorMessage(err));
    }
  }

  async function handleUpload(e: React.ChangeEvent<HTMLInputElement>) {
    const files = e.target.files;
    if (!files?.length) return;
    setActionError(null);
    try {
      for (const file of Array.from(files)) {
        const text = await file.text();
        const path = joinVfsPath(dirPath === "/" ? "/" : dirPath.replace(/\/$/, ""), file.name);
        await createFile.mutateAsync({ path, content: text });
      }
    } catch (err) {
      setActionError(vfsErrorMessage(err));
    } finally {
      e.target.value = "";
    }
  }

  async function handleDelete() {
    if (!deleteTarget) return;
    setActionError(null);
    try {
      await deletePath.mutateAsync(deleteTarget.path);
      if (selectedPath === deleteTarget.path) {
        setSelectedPath(null);
        setEditorContent("");
      }
      setDeleteTarget(null);
    } catch (err) {
      setActionError(vfsErrorMessage(err));
      setDeleteTarget(null);
    }
  }

  function handleDownload(entry: VfsEntry) {
    if (entry.is_dir) return;
    const blob = new Blob([editorContent], { type: "text/plain;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = entry.name;
    a.click();
    URL.revokeObjectURL(url);
  }

  const editorTitle = useMemo(() => {
    if (!selectedPath) return null;
    return selectedPath.split("/").filter(Boolean).pop() ?? selectedPath;
  }, [selectedPath]);

  return {
    dirPath,
    setDirPath: navigateDir,
    selectedPath,
    editorContent,
    setEditorContent,
    editorDirty,
    setEditorDirty,
    actionError,
    showFolderModal,
    setShowFolderModal,
    showNewFileModal,
    setShowNewFileModal,
    folderName,
    setFolderName,
    newFileName,
    setNewFileName,
    deleteTarget,
    setDeleteTarget,
    fileInputRef,
    openDir,
    openFile,
    handleSave,
    handleCreateFolder,
    handleCreateFile,
    handleUpload,
    handleDelete,
    handleDownload,
    editorTitle,
    patchFile,
    resetEditor,
  };
}

export function useVfsEditorSync(
  fileData: VfsFile | undefined,
  editorDirty: boolean,
  setEditorContent: (content: string) => void,
) {
  useEffect(() => {
    if (fileData && !editorDirty) {
      setEditorContent(fileData.content);
    }
  }, [fileData, editorDirty, setEditorContent]);
}
