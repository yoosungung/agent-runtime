import { lazy, Suspense } from "react";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import { QueryClientProvider } from "@tanstack/react-query";
import { ReactQueryDevtools } from "@tanstack/react-query-devtools";
import { queryClient } from "./lib/queryClient";
import { Layout } from "./components/Layout";
import { RequireAuth } from "./components/RequireAuth";
import { RequireNotForcedChangePassword } from "./components/RequireNotForcedChangePassword";
import { RequireAdmin } from "./components/RequireAdmin";
import { ErrorBoundary } from "./components/ErrorBoundary";

const LoginPage = lazy(() =>
  import("./pages/LoginPage").then((m) => ({ default: m.LoginPage })),
);
const DashboardPage = lazy(() =>
  import("./pages/DashboardPage").then((m) => ({ default: m.DashboardPage })),
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
const UserMetaEditPage = lazy(() =>
  import("./pages/UserMetaEditPage").then((m) => ({
    default: m.UserMetaEditPage,
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
                <Route path="/chat" element={<ChatPage />} />

                {/* All admin routes require no forced-password-change + admin role */}
                <Route element={<RequireNotForcedChangePassword />}>
                  <Route element={<RequireAdmin />}>
                    <Route path="/" element={<DashboardPage />} />
                    <Route
                      path="/agents"
                      element={<SourceMetaListPage kind="agent" />}
                    />
                    <Route
                      path="/agents/new"
                      element={<SourceMetaNewPage kind="agent" />}
                    />
                    <Route
                      path="/agents/:id"
                      element={<SourceMetaDetailPage kind="agent" />}
                    />
                    <Route
                      path="/agents/:sourceMetaId/user-meta/:principal"
                      element={<UserMetaEditPage />}
                    />
                    <Route
                      path="/mcp-servers"
                      element={<SourceMetaListPage kind="mcp" />}
                    />
                    <Route
                      path="/mcp-servers/new"
                      element={<SourceMetaNewPage kind="mcp" />}
                    />
                    <Route
                      path="/mcp-servers/:id"
                      element={<SourceMetaDetailPage kind="mcp" />}
                    />
                    <Route
                      path="/mcp-servers/:sourceMetaId/user-meta/:principal"
                      element={<UserMetaEditPage />}
                    />
                    <Route path="/users" element={<UsersListPage />} />
                    <Route path="/users/new" element={<UserNewPage />} />
                    <Route path="/users/:id" element={<UserDetailPage />} />
                    <Route path="/audit" element={<AuditLogPage />} />
                    <Route
                      path="/custom-agents"
                      element={<CustomImageListPage kind="agent" />}
                    />
                    <Route
                      path="/custom-agents/new"
                      element={<CustomImageNewPage kind="agent" />}
                    />
                    <Route
                      path="/custom-mcp"
                      element={<CustomImageListPage kind="mcp" />}
                    />
                    <Route
                      path="/custom-mcp/new"
                      element={<CustomImageNewPage kind="mcp" />}
                    />
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
