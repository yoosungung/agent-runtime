import { useEffect } from "react";
import { useParams } from "react-router-dom";
import { KnowledgeSectionLayout } from "../knowledge/components/KnowledgeSectionLayout";
import { useKnowledgeProjectContext } from "../knowledge/context/KnowledgeProjectContext";

export function FilesLayout() {
  const { projectId } = useParams<{ projectId?: string }>();
  const { setSelectedProjectId } = useKnowledgeProjectContext();

  useEffect(() => {
    if (projectId) {
      setSelectedProjectId(projectId);
    }
  }, [projectId, setSelectedProjectId]);

  const navItems = projectId
    ? [
        {
          to: `/files/projects/${projectId}/documents`,
          label: "Documents",
          end: true,
        },
        {
          to: `/files/projects/${projectId}/lifecycle/tombstones`,
          label: "Tombstones",
        },
        {
          to: `/files/projects/${projectId}/lifecycle/dead-letters`,
          label: "Dead letters",
        },
        {
          to: `/files/projects/${projectId}/lifecycle/maintenance`,
          label: "Maintenance",
        },
      ]
    : [{ to: "/files", label: "Projects", end: true }];

  return (
    <KnowledgeSectionLayout
      section="files"
      title="파일관리"
      projectId={projectId}
      navItems={navItems}
    />
  );
}
