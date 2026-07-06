import { NavLink } from "react-router-dom";

const tabClass = ({ isActive }: { isActive: boolean }) =>
  `px-3 py-1.5 text-sm font-medium rounded transition-colors ${
    isActive
      ? "bg-blue-100 text-blue-800"
      : "text-gray-600 hover:bg-gray-100"
  }`;

export function VfsTabs() {
  return (
    <div className="overflow-x-auto -mx-1 px-1">
      <div className="flex gap-2 mb-6 border-b border-gray-200 pb-3 min-w-max sm:min-w-0">
        <NavLink to="/vfs/agent" className={tabClass}>
          Agent
        </NavLink>
        <NavLink to="/vfs/user" className={tabClass}>
          User
        </NavLink>
        <NavLink to="/vfs/wiki" className={tabClass}>
          Wiki
        </NavLink>
      </div>
    </div>
  );
}
