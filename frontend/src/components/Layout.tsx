import { useEffect, useState } from "react";
import { Link, NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { useSession } from "../hooks/useSession";
import { apiJson } from "../lib/api";
import { queryClient } from "../lib/queryClient";
import { isAdminRole, isDeveloperRole } from "../lib/roles";

const navLinkClass = ({ isActive }: { isActive: boolean }) =>
  `block rounded px-3 py-2 text-sm transition-colors ${
    isActive
      ? "bg-gray-800 text-white font-medium"
      : "text-gray-300 hover:bg-gray-800 hover:text-white"
  }`;

const desktopNavLinkClass = ({ isActive }: { isActive: boolean }) =>
  `text-sm transition-colors whitespace-nowrap ${
    isActive ? "text-white font-medium" : "text-gray-300 hover:text-white"
  }`;

export function Layout() {
  const { data: session } = useSession();
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const [mobileOpen, setMobileOpen] = useState(false);
  const role = session?.role ?? "user";
  const showDeveloper = isDeveloperRole(role);
  const showAdmin = isAdminRole(role);
  const isChatRoute = pathname === "/chat";

  useEffect(() => {
    setMobileOpen(false);
  }, [pathname]);

  const sectionLinkClass = (prefix: string, mobile = false) => {
    const active =
      pathname === prefix || pathname.startsWith(`${prefix}/`);
    if (mobile) {
      return `block rounded px-3 py-2 text-sm transition-colors ${
        active
          ? "bg-gray-800 text-white font-medium"
          : "text-gray-300 hover:bg-gray-800 hover:text-white"
      }`;
    }
    return `text-sm transition-colors whitespace-nowrap ${
      active ? "text-white font-medium" : "text-gray-300 hover:text-white"
    }`;
  };

  async function handleLogout() {
    try {
      await apiJson("/api/auth/logout", { method: "POST" });
    } catch {
      // ignore errors
    }
    queryClient.clear();
    navigate("/login", { replace: true });
  }

  const chatLink = (
    <NavLink to="/chat" className={navLinkClass}>
      Chat
    </NavLink>
  );

  const agentLink = (
    <NavLink to="/agents" className={navLinkClass}>
      Agent
    </NavLink>
  );

  const developerLinks = showDeveloper ? (
    <>
      <NavLink to="/bundle/agents" className={() => sectionLinkClass("/bundle", true)}>
        Bundle
      </NavLink>
      <NavLink to="/container/agents" className={() => sectionLinkClass("/container", true)}>
        Container
      </NavLink>
    </>
  ) : null;

  const adminLinks = showAdmin ? (
    <>
      <NavLink to="/settings/infra" className={navLinkClass}>
        Platform Infra
      </NavLink>
      <NavLink to="/bucket" className={navLinkClass}>
        Bucket
      </NavLink>
      <NavLink to="/users" className={navLinkClass}>
        User
      </NavLink>
      <NavLink to="/audit" className={navLinkClass}>
        Audit
      </NavLink>
    </>
  ) : null;

  const userLinks = (
    <>
      <NavLink to="/me" className={navLinkClass}>
        {session?.username ?? "My Profile"}
      </NavLink>
    </>
  );

  return (
    <div
      className={
        isChatRoute
          ? "h-screen bg-gray-50 flex flex-col overflow-hidden"
          : "min-h-screen bg-gray-50 flex flex-col"
      }
    >
      <nav className="bg-gray-900 text-white shrink-0">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex items-center justify-between min-h-14 py-2 gap-3">
            <div className="flex items-center gap-3 min-w-0">
              <Link
                to="/"
                className="font-semibold text-base sm:text-lg tracking-tight hover:text-gray-300 truncate"
              >
                agents-runtime
              </Link>
              <div className="hidden md:flex items-center gap-4 lg:gap-6">
                <NavLink to="/chat" className={desktopNavLinkClass}>
                  Chat
                </NavLink>
                <NavLink to="/agents" className={desktopNavLinkClass}>
                  Agent
                </NavLink>
                {showDeveloper && (
                  <>
                    <NavLink
                      to="/bundle/agents"
                      className={() => sectionLinkClass("/bundle")}
                    >
                      Bundle
                    </NavLink>
                    <NavLink
                      to="/container/agents"
                      className={() => sectionLinkClass("/container")}
                    >
                      Container
                    </NavLink>
                  </>
                )}
                {showAdmin && (
                  <>
                    <NavLink to="/settings/infra" className={desktopNavLinkClass}>
                      Platform Infra
                    </NavLink>
                    <NavLink to="/bucket" className={desktopNavLinkClass}>
                      Bucket
                    </NavLink>
                    <NavLink to="/users" className={desktopNavLinkClass}>
                      User
                    </NavLink>
                    <NavLink to="/audit" className={desktopNavLinkClass}>
                      Audit
                    </NavLink>
                  </>
                )}
              </div>
            </div>

            <div className="hidden md:flex items-center gap-3 lg:gap-4 shrink-0">
              <NavLink to="/me" className={desktopNavLinkClass}>
                <span className="max-w-[10rem] truncate inline-block align-bottom">
                  {session?.username ?? "My Profile"}
                </span>
              </NavLink>
              <button
                onClick={handleLogout}
                className="text-sm bg-gray-700 hover:bg-gray-600 px-3 py-1 rounded transition-colors whitespace-nowrap"
              >
                Logout
              </button>
            </div>

            <button
              type="button"
              aria-label={mobileOpen ? "Close menu" : "Open menu"}
              aria-expanded={mobileOpen}
              onClick={() => setMobileOpen((open) => !open)}
              className="md:hidden inline-flex items-center justify-center rounded p-2 text-gray-300 hover:bg-gray-800 hover:text-white"
            >
              {mobileOpen ? (
                <svg className="h-6 w-6" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path strokeLinecap="round" d="M6 6l12 12M18 6L6 18" />
                </svg>
              ) : (
                <svg className="h-6 w-6" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path strokeLinecap="round" d="M4 7h16M4 12h16M4 17h16" />
                </svg>
              )}
            </button>
          </div>

          {mobileOpen && (
            <div className="md:hidden border-t border-gray-800 py-3 space-y-1">
              {chatLink}
              {agentLink}
              {developerLinks}
              {adminLinks}
              {userLinks}
              <button
                onClick={handleLogout}
                className="w-full text-left rounded px-3 py-2 text-sm text-gray-300 hover:bg-gray-800 hover:text-white"
              >
                Logout
              </button>
            </div>
          )}
        </div>
      </nav>
      <main
        className={`flex-1 w-full max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 min-h-0 ${
          isChatRoute
            ? "flex flex-col overflow-hidden py-4 sm:py-6"
            : "py-4 sm:py-6"
        }`}
      >
        <Outlet />
      </main>
    </div>
  );
}
