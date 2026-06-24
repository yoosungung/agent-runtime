import { lazy } from "react";
import { Route } from "react-router-dom";

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
  <>
    <Route path="/pipeline/credentials" element={<PipelineCredentialsPage />} />
    <Route path="/pipeline/sources" element={<PipelineSourcesListPage />} />
    <Route path="/pipeline/sources/new" element={<PipelineSourceNewPage />} />
    <Route path="/pipeline/sources/:id" element={<PipelineSourceDetailPage />} />
    <Route path="/pipeline/runs" element={<PipelineRunsPage />} />
  </>
);
