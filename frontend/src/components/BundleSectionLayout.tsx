import { Outlet } from "react-router-dom";
import { useSession } from "../hooks/useSession";
import { isAdminRole } from "../lib/roles";
import { KindTabs } from "./KindTabs";

export function BundleSectionLayout() {
  const { data: session } = useSession();
  const showBucket = isAdminRole(session?.role ?? "user");

  return (
    <div>
      <h1 className="text-xl sm:text-2xl font-bold text-gray-900 mb-4">Bundle</h1>
      <KindTabs basePath="/bundle" showBucket={showBucket} />
      <Outlet />
    </div>
  );
}
