import { lazy } from "react";
import { Navigate, Route } from "react-router-dom";
import { PipelineLayout } from "./PipelineLayout";
import { PipelineProjectShell } from "./components/PipelineProjectShell";

const PipelineLandingPage = lazy(() =>
  import("./pages/PipelineLandingPage").then((m) => ({
    default: m.PipelineLandingPage,
  })),
);
const PipelineSourcesListPage = lazy(() =>
  import("./pages/PipelineSourcesListPage").then((m) => ({
    default: m.PipelineSourcesListPage,
  })),
);
const PipelineSourceNewPage = lazy(() =>
  import("./pages/PipelineSourceNewPage").then((m) => ({
    default: m.PipelineSourceNewPage,
  })),
);
const PipelineSourceDetailPage = lazy(() =>
  import("./pages/PipelineSourceDetailPage").then((m) => ({
    default: m.PipelineSourceDetailPage,
  })),
);
const PipelineRunsPage = lazy(() =>
  import("./pages/PipelineRunsPage").then((m) => ({
    default: m.PipelineRunsPage,
  })),
);
const PipelineDocumentsPage = lazy(() =>
  import("./pages/PipelineDocumentsPage").then((m) => ({
    default: m.PipelineDocumentsPage,
  })),
);
const PipelineDocumentDetailPage = lazy(() =>
  import("./pages/PipelineDocumentDetailPage").then((m) => ({
    default: m.PipelineDocumentDetailPage,
  })),
);
const PipelineMaintenancePage = lazy(() =>
  import("./pages/PipelineMaintenancePage").then((m) => ({
    default: m.PipelineMaintenancePage,
  })),
);
const PipelineCredentialsPage = lazy(() =>
  import("./pages/PipelineCredentialsPage").then((m) => ({
    default: m.PipelineCredentialsPage,
  })),
);

export const pipelineRoutes = (
  <Route path="/pipeline" element={<PipelineLayout />}>
    <Route index element={<PipelineLandingPage />} />
    <Route path="credentials" element={<PipelineCredentialsPage />} />
    <Route path="projects/:projectId" element={<PipelineProjectShell />}>
      <Route index element={<Navigate to="sources" replace />} />
      <Route path="sources" element={<PipelineSourcesListPage />} />
      <Route path="sources/new" element={<PipelineSourceNewPage />} />
      <Route
        path="sources/:sourceId"
        element={<PipelineSourceDetailPage />}
      />
      <Route path="runs" element={<PipelineRunsPage />} />
      <Route path="documents" element={<PipelineDocumentsPage />} />
      <Route
        path="documents/:documentId"
        element={<PipelineDocumentDetailPage />}
      />
      <Route path="maintenance" element={<PipelineMaintenancePage />} />
    </Route>
  </Route>
);
