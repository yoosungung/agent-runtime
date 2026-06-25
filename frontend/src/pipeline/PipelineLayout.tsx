import { useEffect } from "react";
import { useParams } from "react-router-dom";
import { KnowledgeSectionLayout } from "../knowledge/components/KnowledgeSectionLayout";
import { useKnowledgeProjectContext } from "../knowledge/context/KnowledgeProjectContext";

export function PipelineLayout() {
  const { projectId } = useParams<{ projectId?: string }>();
  const { setSelectedProjectId } = useKnowledgeProjectContext();

  useEffect(() => {
    if (projectId) {
      setSelectedProjectId(projectId);
    }
  }, [projectId, setSelectedProjectId]);

  const projectNav = projectId
    ? [
        {
          to: `/pipeline/projects/${projectId}`,
          label: "Overview",
          end: true,
        },
        { to: `/pipeline/projects/${projectId}/sources`, label: "Sources" },
        { to: `/pipeline/projects/${projectId}/runs`, label: "Runs" },
      ]
    : [{ to: "/pipeline", label: "Projects", end: true }];

  return (
    <KnowledgeSectionLayout
      section="pipeline"
      title="Pipeline"
      projectId={projectId}
      navItems={projectNav}
      footerNav={[{ to: "/pipeline/credentials", label: "Credentials" }]}
    />
  );
}
