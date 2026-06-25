import { useEffect } from "react";
import { Outlet, useLocation, useParams } from "react-router-dom";
import { PipelineSidebar } from "./components/PipelineSidebar";
import { useKnowledgeProjectContext } from "../knowledge/context/KnowledgeProjectContext";

export function PipelineLayout() {
  const { projectId } = useParams<{ projectId?: string }>();
  const location = useLocation();
  const { selectedProjectId, setSelectedProjectId } = useKnowledgeProjectContext();

  useEffect(() => {
    if (projectId) {
      setSelectedProjectId(projectId);
    }
  }, [projectId, setSelectedProjectId]);

  const activeProjectId =
    projectId ||
    (location.pathname.match(/\/pipeline\/projects\/([^/]+)/)?.[1] ?? "") ||
    selectedProjectId ||
    "";

  return (
    <div className="flex flex-col lg:flex-row gap-6">
      <PipelineSidebar activeProjectId={activeProjectId} />
      <div className="flex-1 min-w-0">
        <Outlet />
      </div>
    </div>
  );
}
