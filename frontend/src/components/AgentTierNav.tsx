import { NavLink } from "react-router-dom";

const linkClass = ({ isActive }: { isActive: boolean }) =>
  `px-3 py-1.5 text-sm rounded-md transition-colors ${
    isActive
      ? "bg-blue-600 text-white font-medium"
      : "bg-gray-100 text-gray-700 hover:bg-gray-200"
  }`;

export function AgentTierNav() {
  return (
    <div className="flex gap-2 mb-4">
      <NavLink to="/agents" end className={linkClass}>
        General
      </NavLink>
      <NavLink to="/agents/hermes" className={linkClass}>
        Hermes
      </NavLink>
    </div>
  );
}
