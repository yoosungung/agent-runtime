import { lazy } from "react";
import { Route } from "react-router-dom";
import { FilesLayout } from "./FilesLayout";

const FilesProjectsPage = lazy(() =>
  import("./pages/FilesProjectsPage").then((m) => ({
    default: m.FilesProjectsPage,
  })),
);
const FilesDocumentsPage = lazy(() =>
  import("./pages/FilesDocumentsPage").then((m) => ({
    default: m.FilesDocumentsPage,
  })),
);
const FilesDocumentDetailPage = lazy(() =>
  import("./pages/FilesDocumentDetailPage").then((m) => ({
    default: m.FilesDocumentDetailPage,
  })),
);
const FilesTombstonesPage = lazy(() =>
  import("./pages/FilesTombstonesPage").then((m) => ({
    default: m.FilesTombstonesPage,
  })),
);
const FilesDeadLettersPage = lazy(() =>
  import("./pages/FilesDeadLettersPage").then((m) => ({
    default: m.FilesDeadLettersPage,
  })),
);
const FilesMaintenancePage = lazy(() =>
  import("./pages/FilesMaintenancePage").then((m) => ({
    default: m.FilesMaintenancePage,
  })),
);

export const filesRoutes = (
  <Route path="/files" element={<FilesLayout />}>
    <Route index element={<FilesProjectsPage />} />
    <Route path="projects/:projectId/documents" element={<FilesDocumentsPage />} />
    <Route
      path="projects/:projectId/documents/:documentId"
      element={<FilesDocumentDetailPage />}
    />
    <Route
      path="projects/:projectId/lifecycle/tombstones"
      element={<FilesTombstonesPage />}
    />
    <Route
      path="projects/:projectId/lifecycle/dead-letters"
      element={<FilesDeadLettersPage />}
    />
    <Route
      path="projects/:projectId/lifecycle/maintenance"
      element={<FilesMaintenancePage />}
    />
  </Route>
);
