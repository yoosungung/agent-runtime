import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useSession } from "../hooks/useSession";
import { useChangeSelfPassword } from "../hooks/useUsers";
import { queryClient } from "../lib/queryClient";

export function MePage() {
  const navigate = useNavigate();
  const { data: session } = useSession();
  const changePwMut = useChangeSelfPassword();

  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);

    if (newPassword.length < 12) {
      setError("New password must be at least 12 characters");
      return;
    }
    if (newPassword !== confirmPassword) {
      setError("Passwords do not match");
      return;
    }

    try {
      await changePwMut.mutateAsync({
        current_password: currentPassword,
        new_password: newPassword,
      });
      setSuccess(true);
      // Auto logout after password change
      setTimeout(() => {
        queryClient.clear();
        navigate("/login", { replace: true });
      }, 2000);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to change password");
    }
  }

  return (
    <div>
      <h1 className="text-2xl font-bold text-gray-900 mb-6">My Profile</h1>

      {session?.must_change_password && (
        <div className="mb-6 bg-amber-50 border border-amber-300 rounded px-4 py-4">
          <p className="text-sm font-medium text-amber-800">
            You must change your password to continue using the system.
          </p>
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Session info */}
        <div className="bg-white shadow rounded-lg p-6">
          <h2 className="text-base font-semibold text-gray-900 mb-4">
            Account Info
          </h2>
          <div className="space-y-3">
            <div>
              <p className="text-xs text-gray-500">Username</p>
              <p className="text-sm font-medium text-gray-900">
                {session?.username}
              </p>
            </div>
            <div>
              <p className="text-xs text-gray-500">Tenant</p>
              <p className="text-sm text-gray-900">
                {session?.tenant ?? "-"}
              </p>
            </div>
            <div>
              <p className="text-xs text-gray-500">Role</p>
              <p className="text-sm">
                {session?.is_admin ? (
                  <span className="bg-purple-100 text-purple-800 text-xs font-medium px-2 py-0.5 rounded">
                    Admin
                  </span>
                ) : (
                  <span className="bg-gray-100 text-gray-700 text-xs font-medium px-2 py-0.5 rounded">
                    User
                  </span>
                )}
              </p>
            </div>
          </div>
        </div>

        {/* Change password */}
        <div className="bg-white shadow rounded-lg p-6">
          <h2 className="text-base font-semibold text-gray-900 mb-4">
            Change Password
          </h2>

          {success ? (
            <div className="bg-green-50 border border-green-200 rounded px-4 py-4">
              <p className="text-sm text-green-700 font-medium">
                Password changed successfully. Logging you out...
              </p>
            </div>
          ) : (
            <form onSubmit={handleSubmit} className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Current Password
                </label>
                <input
                  type="password"
                  value={currentPassword}
                  onChange={(e) => setCurrentPassword(e.target.value)}
                  required
                  className="border border-gray-300 rounded px-3 py-2 w-full focus:outline-none focus:ring-2 focus:ring-blue-500"
                  autoComplete="current-password"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  New Password
                </label>
                <input
                  type="password"
                  value={newPassword}
                  onChange={(e) => setNewPassword(e.target.value)}
                  required
                  className="border border-gray-300 rounded px-3 py-2 w-full focus:outline-none focus:ring-2 focus:ring-blue-500"
                  autoComplete="new-password"
                />
                <div className="flex justify-between mt-1">
                  <p className="text-xs text-gray-400">Minimum 12 characters</p>
                  <p
                    className={`text-xs ${newPassword.length < 12 ? "text-amber-500" : "text-green-600"}`}
                  >
                    {newPassword.length}/12+
                  </p>
                </div>
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Confirm New Password
                </label>
                <input
                  type="password"
                  value={confirmPassword}
                  onChange={(e) => setConfirmPassword(e.target.value)}
                  required
                  className="border border-gray-300 rounded px-3 py-2 w-full focus:outline-none focus:ring-2 focus:ring-blue-500"
                  autoComplete="new-password"
                />
                {confirmPassword && newPassword !== confirmPassword && (
                  <p className="text-xs text-red-600 mt-1">
                    Passwords do not match
                  </p>
                )}
              </div>

              {error && (
                <p className="text-sm text-red-600 bg-red-50 border border-red-200 rounded px-3 py-2">
                  {error}
                </p>
              )}

              <button
                type="submit"
                disabled={changePwMut.isPending}
                className="w-full bg-blue-600 text-white px-4 py-2 rounded hover:bg-blue-700 disabled:opacity-50 font-medium"
              >
                {changePwMut.isPending ? "Changing..." : "Change Password"}
              </button>
            </form>
          )}
        </div>
      </div>
    </div>
  );
}
