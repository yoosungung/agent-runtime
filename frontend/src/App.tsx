import { lazy, Suspense } from "react";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { QueryClientProvider } from "@tanstack/react-query";
import { ReactQueryDevtools } from "@tanstack/react-query-devtools";
import { queryClient } from "./lib/queryClient";
import { Layout } from "./components/Layout";
import { BundleSectionLayout } from "./components/BundleSectionLayout";
import { ContainerSectionLayout } from "./components/ContainerSectionLayout";
import { RequireAuth } from "./components/RequireAuth";
import { RequireNotForcedChangePassword } from "./components/RequireNotForcedChangePassword";
import { RequireRole } from "./components/RequireRole";
import { HomeRedirect } from "./components/HomeRedirect";
import { ErrorBoundary } from "./components/ErrorBoundary";

const LoginPage = lazy(() =>
  import("./pages/LoginPage").then((m) => ({ default: m.LoginPage })),
);
const SourceMetaListPage = lazy(() =>
  import("./pages/SourceMetaListPage").then((m) => ({
    default: m.SourceMetaListPage,
  })),
);
const SourceMetaNewPage = lazy(() =>
  import("./pages/SourceMetaNewPage").then((m) => ({
    default: m.SourceMetaNewPage,
  })),
);
const SourceMetaDetailPage = lazy(() =>
  import("./pages/SourceMetaDetailPage").then((m) => ({
    default: m.SourceMetaDetailPage,
  })),
);
const UsersListPage = lazy(() =>
  import("./pages/UsersListPage").then((m) => ({ default: m.UsersListPage })),
);
const UserNewPage = lazy(() =>
  import("./pages/UserNewPage").then((m) => ({ default: m.UserNewPage })),
);
const UserDetailPage = lazy(() =>
  import("./pages/UserDetailPage").then((m) => ({
    default: m.UserDetailPage,
  })),
);
const MePage = lazy(() =>
  import("./pages/MePage").then((m) => ({ default: m.MePage })),
);
const ChatPage = lazy(() =>
  import("./pages/ChatPage").then((m) => ({ default: m.ChatPage })),
);
const AuditLogPage = lazy(() =>
  import("./pages/AuditLogPage").then((m) => ({ default: m.AuditLogPage })),
);
const InfraMetaPage = lazy(() =>
  import("./pages/InfraMetaPage").then((m) => ({ default: m.InfraMetaPage })),
);
const GeneralAgentNewPage = lazy(() =>
  import("./pages/GeneralAgentNewPage").then((m) => ({
    default: m.GeneralAgentNewPage,
  })),
);
const CustomImageListPage = lazy(() =>
  import("./pages/CustomImageListPage").then((m) => ({
    default: m.CustomImageListPage,
  })),
);
const CustomImageNewPage = lazy(() =>
  import("./pages/CustomImageNewPage").then((m) => ({
    default: m.CustomImageNewPage,
  })),
);
const CustomImageEditPage = lazy(() =>
  import("./pages/CustomImageEditPage").then((m) => ({
    default: m.CustomImageEditPage,
  })),
);

function PageFallback() {
  return (
    <div className="flex items-center justify-center h-32">
      <div className="text-sm text-gray-400">Loading...</div>
    </div>
  );
}

export function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <ErrorBoundary>
        <BrowserRouter>
          <Suspense fallback={<PageFallback />}>
            <Routes>
              <Route path="/login" element={<LoginPage />} />
              <Route
                element={
                  <RequireAuth>
                    <Layout />
                  </RequireAuth>
                }
              >
                {/* /me and /chat accessible even during forced password change */}
                <Route path="/me" element={<MePage />} />
                <Route
                  path="/me/integrations"
                  element={<Navigate to="/me" replace />}
                />
                <Route
                  path="/me/user-meta/:kind/:name"
                  element={<MePage />}
                />
                <Route path="/chat" element={<ChatPage />} />

                <Route element={<RequireNotForcedChangePassword />}>
                  <Route path="/" element={<HomeRedirect />} />
                  <Route
                    path="/agents"
                    element={
                      <SourceMetaListPage kind="agent" deployMode="general" />
                    }
                  />
                  <Route
                    path="/agents/new/general"
                    element={<GeneralAgentNewPage />}
                  />
                  <Route
                    path="/agents/new"
                    element={<Navigate to="/bundle/agents/new" replace />}
                  />
                  <Route
                    path="/agents/:id"
                    element={<SourceMetaDetailPage kind="agent" />}
                  />

                  <Route element={<RequireRole min="developer" />}>
                    <Route path="/bundle" element={<Navigate to="/bundle/agents" replace />} />
                    <Route element={<BundleSectionLayout />}>
                      <Route
                        path="/bundle/agents"
                        element={
                          <SourceMetaListPage
                            kind="agent"
                            deployMode="bundle"
                            embedded
                          />
                        }
                      />
                      <Route
                        path="/bundle/mcp"
                        element={
                          <SourceMetaListPage
                            kind="mcp"
                            deployMode="bundle"
                            embedded
                          />
                        }
                      />
                    </Route>
                    <Route
                      path="/bundle/agents/new"
                      element={<SourceMetaNewPage kind="agent" />}
                    />
                    <Route
                      path="/bundle/mcp/new"
                      element={<SourceMetaNewPage kind="mcp" />}
                    />
                    <Route
                      path="/mcp-servers/:id"
                      element={<SourceMetaDetailPage kind="mcp" />}
                    />

                    <Route path="/container" element={<Navigate to="/container/agents" replace />} />
                    <Route element={<ContainerSectionLayout />}>
                      <Route
                        path="/container/agents"
                        element={<CustomImageListPage kind="agent" embedded />}
                      />
                      <Route
                        path="/container/mcp"
                        element={<CustomImageListPage kind="mcp" embedded />}
                      />
                    </Route>
                    <Route
                      path="/container/agents/new"
                      element={<CustomImageNewPage kind="agent" />}
                    />
                    <Route
                      path="/container/mcp/new"
                      element={<CustomImageNewPage kind="mcp" />}
                    />
                    <Route
                      path="/container/agents/:slug/edit"
                      element={<CustomImageEditPage kind="agent" />}
                    />
                    <Route
                      path="/container/mcp/:slug/edit"
                      element={<CustomImageEditPage kind="mcp" />}
                    />

                    <Route path="/mcp-servers" element={<Navigate to="/bundle/mcp" replace />} />
                    <Route path="/mcp-servers/new" element={<Navigate to="/bundle/mcp/new" replace />} />
                    <Route path="/custom-agents" element={<Navigate to="/container/agents" replace />} />
                    <Route path="/custom-agents/new" element={<Navigate to="/container/agents/new" replace />} />
                    <Route path="/custom-mcp" element={<Navigate to="/container/mcp" replace />} />
                    <Route path="/custom-mcp/new" element={<Navigate to="/container/mcp/new" replace />} />
                  </Route>

                  <Route element={<RequireRole min="admin" />}>
                    <Route path="/users" element={<UsersListPage />} />
                    <Route path="/users/new" element={<UserNewPage />} />
                    <Route path="/users/:id" element={<UserDetailPage />} />
                    <Route path="/audit" element={<AuditLogPage />} />
                    <Route path="/settings/infra" element={<InfraMetaPage />} />
                  </Route>
                </Route>
              </Route>
            </Routes>
          </Suspense>
        </BrowserRouter>
      </ErrorBoundary>
      <ReactQueryDevtools initialIsOpen={false} />
    </QueryClientProvider>
  );
}
