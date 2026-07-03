import { Link } from "react-router-dom";
import { PageHeader } from "../components/PageHeader";

export function VfsLandingPage() {
  return (
    <div>
      <PageHeader title="VFS" />
      <p className="mb-6 text-sm text-gray-600">
        Postgres-backed virtual filesystem — Agent 공유 영역, User 개인 영역, Wiki project
        스코프.
      </p>
      <div className="grid gap-4 sm:grid-cols-3">
        <Link
          to="/vfs/agent"
          className="rounded-lg border border-gray-200 bg-white p-5 shadow-sm hover:border-blue-300"
        >
          <h2 className="text-lg font-semibold">Agent</h2>
          <p className="mt-2 text-sm text-gray-600">
            General agent <code className="text-xs">/agent/</code> 공유 파일
          </p>
        </Link>
        <Link
          to="/vfs/user"
          className="rounded-lg border border-gray-200 bg-white p-5 shadow-sm hover:border-blue-300"
        >
          <h2 className="text-lg font-semibold">User</h2>
          <p className="mt-2 text-sm text-gray-600">
            사용자별 <code className="text-xs">/user/</code> 개인 VFS
          </p>
        </Link>
        <Link
          to="/vfs/wiki"
          className="rounded-lg border border-gray-200 bg-white p-5 shadow-sm hover:border-blue-300"
        >
          <h2 className="text-lg font-semibold">Wiki</h2>
          <p className="mt-2 text-sm text-gray-600">
            Knowledge project별 컴파일드 wiki (<code className="text-xs">vfs_wiki_files</code>)
          </p>
        </Link>
      </div>
    </div>
  );
}
