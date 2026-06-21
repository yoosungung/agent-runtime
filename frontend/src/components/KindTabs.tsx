import { NavLink } from "react-router-dom";

interface Props {
  basePath: "/bundle" | "/container";
  /** Bundle section only: admin-only Bucket object store tab */
  showBucket?: boolean;
}

const tabClass = ({ isActive }: { isActive: boolean }) =>
  `px-3 py-1.5 text-sm font-medium rounded transition-colors ${
    isActive
      ? "bg-blue-100 text-blue-800"
      : "text-gray-600 hover:bg-gray-100"
  }`;

export function KindTabs({ basePath, showBucket = false }: Props) {
  return (
    <div className="overflow-x-auto -mx-1 px-1">
    <div className="flex gap-2 mb-6 border-b border-gray-200 pb-3 min-w-max sm:min-w-0">
      <NavLink to={`${basePath}/agents`} className={tabClass} end>
        Agent
      </NavLink>
      <NavLink to={`${basePath}/mcp`} className={tabClass}>
        MCP
      </NavLink>
      {showBucket && basePath === "/bundle" && (
        <NavLink to={`${basePath}/bucket`} className={tabClass}>
          Bucket
        </NavLink>
      )}
    </div>
    </div>
  );
}
