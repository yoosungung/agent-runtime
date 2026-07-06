import { Outlet } from "react-router-dom";
import { VfsTabs } from "./VfsTabs";

export function VfsSectionLayout() {
  return (
    <div>
      <h1 className="text-xl sm:text-2xl font-bold text-gray-900 mb-2">VFS</h1>
      <p className="mb-4 text-sm text-gray-600">
        Postgres-backed virtual filesystem — Agent 공유 영역, User 개인 영역, Wiki project
        스코프.
      </p>
      <VfsTabs />
      <Outlet />
    </div>
  );
}
