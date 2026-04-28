import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { useUsersList } from "../hooks/useUsers";
import { Paginator } from "../components/Paginator";
import { usePagination } from "../hooks/usePagination";

function formatDate(iso: string): string {
  return new Date(iso).toLocaleString();
}

export function UsersListPage() {
  const navigate = useNavigate();
  const { limit, offset, setOffset, reset } = usePagination(50);
  const [usernameFilter, setUsernameFilter] = useState("");
  const [debouncedUsername, setDebouncedUsername] = useState("");
  const [disabledFilter, setDisabledFilter] = useState<boolean | undefined>(
    undefined,
  );

  useEffect(() => {
    const t = setTimeout(() => {
      setDebouncedUsername(usernameFilter);
      reset();
    }, 300);
    return () => clearTimeout(t);
  }, [usernameFilter, reset]);

  const { data, isLoading, isError } = useUsersList({
    username: debouncedUsername || undefined,
    disabled: disabledFilter,
    limit,
    offset,
  });

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold text-gray-900">Users</h1>
        <button
          onClick={() => navigate("/users/new")}
          className="bg-blue-600 text-white px-4 py-2 rounded hover:bg-blue-700 text-sm font-medium"
        >
          + New User
        </button>
      </div>

      {/* Filters */}
      <div className="bg-white shadow rounded-lg p-4 mb-4 flex gap-4 items-end flex-wrap">
        <div>
          <label className="block text-xs text-gray-500 mb-1">
            Username prefix
          </label>
          <input
            type="text"
            value={usernameFilter}
            onChange={(e) => setUsernameFilter(e.target.value)}
            placeholder="Filter by username..."
            className="border border-gray-300 rounded px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
        </div>
        <div>
          <label className="block text-xs text-gray-500 mb-1">Status</label>
          <select
            value={
              disabledFilter === undefined
                ? ""
                : disabledFilter
                  ? "true"
                  : "false"
            }
            onChange={(e) => {
              const v = e.target.value;
              setDisabledFilter(v === "" ? undefined : v === "true");
              reset();
            }}
            className="border border-gray-300 rounded px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            <option value="">All</option>
            <option value="false">Active</option>
            <option value="true">Disabled</option>
          </select>
        </div>
      </div>

      <div className="bg-white shadow rounded-lg overflow-hidden">
        {isLoading && (
          <p className="p-4 text-sm text-gray-500">Loading...</p>
        )}
        {isError && (
          <p className="p-4 text-sm text-red-500">Failed to load users.</p>
        )}
        {!isLoading && !isError && (
          <>
            <div className="overflow-x-auto">
              <table className="min-w-full divide-y divide-gray-200">
                <thead>
                  <tr>
                    <th className="bg-gray-50 px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                      Username
                    </th>
                    <th className="bg-gray-50 px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                      Tenant
                    </th>
                    <th className="bg-gray-50 px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                      Role
                    </th>
                    <th className="bg-gray-50 px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                      Status
                    </th>
                    <th className="bg-gray-50 px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                      Created
                    </th>
                  </tr>
                </thead>
                <tbody className="bg-white divide-y divide-gray-200">
                  {data?.items.length === 0 && (
                    <tr>
                      <td
                        colSpan={5}
                        className="px-4 py-8 text-sm text-gray-500 text-center"
                      >
                        No users found.
                      </td>
                    </tr>
                  )}
                  {data?.items.map((user) => (
                    <tr
                      key={user.id}
                      onClick={() => navigate(`/users/${user.id}`)}
                      className="hover:bg-gray-50 cursor-pointer"
                    >
                      <td className="px-4 py-3 text-sm font-medium text-gray-900">
                        {user.username}
                      </td>
                      <td className="px-4 py-3 text-sm text-gray-600">
                        {user.tenant ?? "-"}
                      </td>
                      <td className="px-4 py-3 text-sm">
                        {user.is_admin && (
                          <span className="bg-purple-100 text-purple-800 text-xs font-medium px-2 py-0.5 rounded">
                            Admin
                          </span>
                        )}
                      </td>
                      <td className="px-4 py-3 text-sm">
                        {user.disabled ? (
                          <span className="bg-red-100 text-red-800 text-xs font-medium px-2 py-0.5 rounded">
                            Disabled
                          </span>
                        ) : (
                          <span className="bg-green-100 text-green-800 text-xs font-medium px-2 py-0.5 rounded">
                            Active
                          </span>
                        )}
                      </td>
                      <td className="px-4 py-3 text-sm text-gray-500">
                        {formatDate(user.created_at)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {data && (
              <div className="border-t border-gray-200 px-4">
                <Paginator
                  total={data.total}
                  limit={limit}
                  offset={offset}
                  onOffsetChange={setOffset}
                />
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
