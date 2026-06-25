import { lazy } from "react";
import { Route } from "react-router-dom";
import { PipelineLayout } from "./PipelineLayout";

const PipelineProjectsPage = lazy(() =>
  import("./pages/PipelineProjectsPage").then((m) => ({
    default: m.PipelineProjectsPage,
  })),
);
const PipelineProjectOverviewPage = lazy(() =>
  import("./pages/PipelineProjectOverviewPage").then((m) => ({
    default: m.PipelineProjectOverviewPage,
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
const PipelineCredentialsPage = lazy(() =>
  import("./pages/PipelineCredentialsPage").then((m) => ({
    default: m.PipelineCredentialsPage,
  })),
);

export const pipelineRoutes = (
  <Route path="/pipeline" element={<PipelineLayout />}>
    <Route index element={<PipelineProjectsPage />} />
    <Route path="projects/:projectId" element={<PipelineProjectOverviewPage />} />
    <Route path="projects/:projectId/sources" element={<PipelineSourcesListPage />} />
    <Route path="projects/:projectId/sources/new" element={<PipelineSourceNewPage />} />
    <Route
      path="projects/:projectId/sources/:sourceId"
      element={<PipelineSourceDetailPage />}
    />
    <Route path="projects/:projectId/runs" element={<PipelineRunsPage />} />
    <Route path="credentials" element={<PipelineCredentialsPage />} />
  </Route>
);
