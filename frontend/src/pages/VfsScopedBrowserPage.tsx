import { useLocation, useNavigate, useParams } from "react-router-dom";
import { VfsBrowserView } from "../components/VfsBrowserView";
import { usePipelineProject } from "../pipeline/hooks/usePipeline";
import {
  useCreateVfsUserFile,
  useCreateVfsUserFolder,
  useCreateVfsWikiFile,
  useCreateVfsWikiFolder,
  useDeleteVfsUserPath,
  useDeleteVfsWikiPath,
  usePatchVfsUserFile,
  usePatchVfsWikiFile,
  useVfsUserEntries,
  useVfsUserFile,
  useVfsWikiEntries,
  useVfsWikiFile,
} from "../hooks/useVfs";
import { useVfsBrowserController, useVfsEditorSync } from "../hooks/useVfsBrowserController";

type VfsScope = "user" | "wiki";

function useScopedVfsMutations(scope: VfsScope, id: string) {
  const createUserFile = useCreateVfsUserFile(id);
  const patchUser = usePatchVfsUserFile(id);
  const deleteUser = useDeleteVfsUserPath(id);
  const createUserFolder = useCreateVfsUserFolder(id);
  const createWikiFile = useCreateVfsWikiFile(id);
  const patchWiki = usePatchVfsWikiFile(id);
  const deleteWiki = useDeleteVfsWikiPath(id);
  const createWikiFolder = useCreateVfsWikiFolder(id);

  if (scope === "user") {
    return {
      createFile: createUserFile,
      patchFile: patchUser,
      deletePath: deleteUser,
      createFolder: createUserFolder,
    };
  }
  return {
    createFile: createWikiFile,
    patchFile: patchWiki,
    deletePath: deleteWiki,
    createFolder: createWikiFolder,
  };
}

function useScopedVfsQueries(
  scope: VfsScope,
  id: string,
  dirPath: string,
  selectedPath: string | null,
) {
  const isUser = scope === "user";
  const userEntries = useVfsUserEntries(id, dirPath, isUser);
  const wikiEntries = useVfsWikiEntries(id, dirPath, !isUser);
  const userFile = useVfsUserFile(id, selectedPath, isUser);
  const wikiFile = useVfsWikiFile(id, selectedPath, !isUser);

  if (scope === "user") {
    return { entries: userEntries, file: userFile };
  }
  return { entries: wikiEntries, file: wikiFile };
}

export function VfsScopedBrowserPage({ scope }: { scope: VfsScope }) {
  const { id = "" } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const location = useLocation();
  const username = (location.state as { username?: string } | null)?.username;
  const { data: wikiProject } = usePipelineProject(scope === "wiki" ? id : undefined);

  const mutations = useScopedVfsMutations(scope, id);
  const controller = useVfsBrowserController(mutations);
  const { entries, file } = useScopedVfsQueries(
    scope,
    id,
    controller.dirPath,
    controller.selectedPath,
  );
  useVfsEditorSync(file.data, controller.editorDirty, controller.setEditorContent);

  const entityName =
    scope === "user" ? (username ?? `User ${id}`) : (wikiProject?.name ?? id);
  const home = scope === "user" ? "/vfs/user" : "/vfs/wiki";
  const backLabel = scope === "user" ? "User" : "Wiki";

  return (
    <VfsBrowserView
      backLabel={backLabel}
      onBack={() => navigate(home)}
      entityName={entityName}
      mountLabel={scope === "user" ? "/user/" : (wikiProject?.slug ? `/wiki/${wikiProject.slug}/` : "/wiki/")}
      scopeBadge={scope === "user" ? "Personal VFS" : "Wiki VFS"}
      settingsLink={
        scope === "wiki" && id
          ? { to: `/pipeline/projects/${id}/sources`, label: "Project settings" }
          : undefined
      }
      emptyFolderMessage={
        scope === "user"
          ? "Empty folder — create a file for this user's personal VFS."
          : "Empty folder — create a wiki page file for this project."
      }
      deleteFileDescription={
        scope === "user"
          ? "This file will be permanently removed from the user VFS."
          : "This file will be permanently removed from the wiki VFS."
      }
      deleteFolderDescription="This deletes the folder and all files under it."
      items={entries.data?.items ?? []}
      isLoading={entries.isLoading}
      isError={entries.isError}
      fileLoading={file.isLoading}
      controller={controller}
    />
  );
}
