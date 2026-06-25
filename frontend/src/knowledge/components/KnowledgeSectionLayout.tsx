import { Link, NavLink, Outlet } from "react-router-dom";
import { ProjectSwitcher } from "./ProjectSwitcher";
import { useKnowledgeProjectContext } from "../context/KnowledgeProjectContext";

type NavItem = { to: string; label: string; end?: boolean };

type Props = {
  section: "pipeline" | "files";
  title: string;
  projectId?: string;
  navItems: NavItem[];
  footerNav?: NavItem[];
};

const linkClass = ({ isActive }: { isActive: boolean }) =>
  `block rounded px-3 py-2 text-sm ${
    isActive
      ? "bg-blue-50 text-blue-700 font-medium"
      : "text-gray-700 hover:bg-gray-50"
  }`;

export function KnowledgeSectionLayout({
  section,
  title,
  projectId,
  navItems,
  footerNav = [],
}: Props) {
  const { setSelectedProjectId } = useKnowledgeProjectContext();

  return (
    <div className="flex flex-col lg:flex-row gap-6">
      <aside className="w-full lg:w-56 shrink-0">
        <h2 className="text-lg font-semibold text-gray-900 mb-3">{title}</h2>
        <ProjectSwitcher basePath={section} />
        <nav className="space-y-1">
          {navItems.map((item) => (
            <NavLink key={item.to} to={item.to} end={item.end} className={linkClass}>
              {item.label}
            </NavLink>
          ))}
        </nav>
        {footerNav.length > 0 && (
          <nav className="mt-6 pt-4 border-t border-gray-200 space-y-1">
            {footerNav.map((item) => (
              <NavLink key={item.to} to={item.to} end={item.end} className={linkClass}>
                {item.label}
              </NavLink>
            ))}
          </nav>
        )}
        {projectId && section === "pipeline" && (
          <p className="mt-4 text-xs text-gray-500">
            <Link
              to={`/files/projects/${projectId}/documents`}
              className="text-blue-600 hover:underline"
            >
              파일관리에서 문서 보기
            </Link>
          </p>
        )}
        {projectId && section === "files" && (
          <p className="mt-4 text-xs text-gray-500">
            <Link
              to={`/pipeline/projects/${projectId}/sources`}
              className="text-blue-600 hover:underline"
            >
              Pipeline에서 source 관리
            </Link>
          </p>
        )}
        {projectId && (
          <div className="mt-4 pt-4 border-t border-gray-200">
            <Link
              to="/pipeline"
              onClick={() => setSelectedProjectId("")}
              className="text-xs text-blue-600 hover:underline flex items-center gap-1"
            >
              ← Back to Projects
            </Link>
          </div>
        )}
      </aside>
      <div className="flex-1 min-w-0">
        <Outlet />
      </div>
    </div>
  );
}

