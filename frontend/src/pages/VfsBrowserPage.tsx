import { useLocation, useNavigate, useParams } from "react-router-dom";
import { VfsBrowserView } from "../components/VfsBrowserView";
import {
  useCreateVfsFile,
  useCreateVfsFolder,
  useDeleteVfsPath,
  usePatchVfsFile,
  useVfsEntries,
  useVfsFile,
} from "../hooks/useVfs";
import { useVfsBrowserController, useVfsEditorSync } from "../hooks/useVfsBrowserController";

export function VfsBrowserPage() {
  const { kind = "agent", name = "" } = useParams<{ kind: string; name: string }>();
  const navigate = useNavigate();
  const location = useLocation();
  const deployMode = (location.state as { deploy_mode?: string } | null)?.deploy_mode;
  const isHermes = deployMode === "hermes_general";
  const decodedName = decodeURIComponent(name);

  const createFile = useCreateVfsFile(kind, decodedName);
  const patchFile = usePatchVfsFile(kind, decodedName);
  const deletePath = useDeleteVfsPath(kind, decodedName);
  const createFolder = useCreateVfsFolder(kind, decodedName);
  const controller = useVfsBrowserController({
    createFile,
    patchFile,
    deletePath,
    createFolder,
  });

  const { data, isLoading, isError } = useVfsEntries(kind, decodedName, controller.dirPath);
  const { data: fileData, isLoading: fileLoading } = useVfsFile(
    kind,
    decodedName,
    controller.selectedPath,
  );
  useVfsEditorSync(fileData, controller.editorDirty, controller.setEditorContent);

  return (
    <VfsBrowserView
      backLabel="Agent"
      onBack={() => navigate("/vfs/agent")}
      entityName={decodedName}
      mountLabel={isHermes ? "/profile/" : "/agent/"}
      scopeBadge="Shared VFS"
      settingsLink={{ to: "/agents", label: "Agent settings" }}
      emptyFolderMessage="Empty folder — create a file to seed the agent knowledge base."
      deleteFileDescription="This file will be permanently removed from the agent VFS."
      deleteFolderDescription="This deletes the folder and all files under it."
      items={data?.items ?? []}
      isLoading={isLoading}
      isError={isError}
      fileLoading={fileLoading}
      controller={controller}
    />
  );
}
