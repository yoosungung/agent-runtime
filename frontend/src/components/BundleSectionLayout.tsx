import { Outlet } from "react-router-dom";
import { KindTabs } from "./KindTabs";

export function BundleSectionLayout() {
  return (
    <div>
      <h1 className="text-xl sm:text-2xl font-bold text-gray-900 mb-4">Bundle</h1>
      <KindTabs basePath="/bundle" />
      <Outlet />
    </div>
  );
}
