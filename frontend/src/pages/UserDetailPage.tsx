import { useState, useEffect } from "react";
import { useParams, useNavigate } from "react-router-dom";
import {
  useUserById,
  usePatchUser,
  useChangePassword,
  useDeleteUser,
} from "../hooks/useUsers";
import { AccessList } from "../components/AccessList";
import { ConfirmDialog } from "../components/ConfirmDialog";
import type { UserRole } from "../lib/roles";
import { roleAtLeast } from "../lib/roles";

function formatDate(iso: string): string {
  return new Date(iso).toLocaleString();
}

export function UserDetailPage() {
  const { id } = useParams<{ id: string }>();
  const numId = Number(id);
  const navigate = useNavigate();

  const { data: user, isLoading, isError, refetch } = useUserById(numId);
  const patchMut = usePatchUser(numId, user?.updated_at);
  const changePasswordMut = useChangePassword(numId);
  const deleteMut = useDeleteUser(numId);

  // Editable fields
  const [tenant, setTenant] = useState("");
  const [role, setRole] = useState<UserRole>("user");
  const [disabled, setDisabled] = useState(false);
  const [initialized, setInitialized] = useState(false);

  const [saveError, setSaveError] = useState<string | null>(null);
  const [saveSuccess, setSaveSuccess] = useState(false);

  // Dialogs
  const [deleteDialog, setDeleteDialog] = useState(false);
  const [disableConfirmDialog, setDisableConfirmDialog] = useState(false);
  const [roleConfirmDialog, setRoleConfirmDialog] = useState(false);
  const [pendingDisabled, setPendingDisabled] = useState<boolean | null>(null);
  const [pendingRole, setPendingRole] = useState<UserRole | null>(null);

  // Password reset
  const [passwordDialog, setPasswordDialog] = useState(false);
  const [newPassword, setNewPassword] = useState("");
  const [passwordError, setPasswordError] = useState<string | null>(null);

  useEffect(() => {
    if (!initialized && user) {
      setTenant(user.tenant ?? "");
      setRole(user.role);
      setDisabled(user.disabled);
      setInitialized(true);
    }
  }, [user, initialized]);

  function handleDisabledToggle(val: boolean) {
    if (val || !val) {
      setPendingDisabled(val);
      setDisableConfirmDialog(true);
    }
  }

  function handleRoleChange(nextRole: UserRole) {
    if (nextRole === role) return;
    setPendingRole(nextRole);
    setRoleConfirmDialog(true);
  }

  async function confirmRoleChange() {
    if (pendingRole === null) return;
    setRole(pendingRole);
    setRoleConfirmDialog(false);
    setPendingRole(null);
  }

  async function confirmDisabledChange() {
    if (pendingDisabled === null) return;
    setDisabled(pendingDisabled);
    setDisableConfirmDialog(false);
    setPendingDisabled(null);
  }

  async function handleSave() {
    setSaveError(null);
    setSaveSuccess(false);
    try {
      await patchMut.mutateAsync({
        tenant: tenant || undefined,
        disabled,
        role,
      });
      setSaveSuccess(true);
    } catch (e: unknown) {
      const err = e as { status?: number; message?: string };
      if (err?.status === 412) {
        setSaveError("누군가 먼저 수정했습니다. 새로고침 후 다시 시도하세요.");
        refetch();
      } else {
        setSaveError((err as Error)?.message ?? "Save failed");
      }
    }
  }

  async function handleDelete() {
    try {
      await deleteMut.mutateAsync();
      navigate("/users", { replace: true });
    } catch (e: unknown) {
      setSaveError(e instanceof Error ? e.message : "Delete failed");
      setDeleteDialog(false);
    }
  }

  async function handlePasswordReset() {
    setPasswordError(null);
    if (newPassword.length < 12) {
      setPasswordError("Password must be at least 12 characters");
      return;
    }
    try {
      await changePasswordMut.mutateAsync({ new_password: newPassword });
      setPasswordDialog(false);
      setNewPassword("");
      setSaveSuccess(true);
    } catch (e: unknown) {
      setPasswordError(e instanceof Error ? e.message : "Failed to change password");
    }
  }

  if (isLoading) return <p className="p-4 text-sm text-gray-500">Loading...</p>;
  if (isError || !user)
    return <p className="p-4 text-sm text-red-500">Failed to load user.</p>;

  return (
    <div>
      <div className="flex items-center gap-2 mb-6">
        <button
          onClick={() => navigate("/users")}
          className="text-sm text-blue-600 hover:underline"
        >
          Users
        </button>
        <span className="text-gray-400">/</span>
        <h1 className="text-2xl font-bold text-gray-900">{user.username}</h1>
        {user.disabled && (
          <span className="bg-red-100 text-red-800 text-xs font-medium px-2 py-0.5 rounded">
            Disabled
          </span>
        )}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 mb-6">
        {/* Profile card */}
        <div className="lg:col-span-2 bg-white shadow rounded-lg p-6">
          <h2 className="text-base font-semibold text-gray-900 mb-4">
            Profile
          </h2>

          {/* Readonly fields */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 mb-6">
            {[
              ["ID", String(user.id)],
              ["Username", user.username],
              ["Created", formatDate(user.created_at)],
              ["Updated", formatDate(user.updated_at)],
            ].map(([label, value]) => (
              <div key={label}>
                <p className="text-xs text-gray-500">{label}</p>
                <p className="text-sm text-gray-900">{value}</p>
              </div>
            ))}
          </div>

          {/* Editable fields */}
          <div className="space-y-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Tenant
              </label>
              <input
                value={tenant}
                onChange={(e) => setTenant(e.target.value)}
                className="border border-gray-300 rounded px-3 py-2 w-full focus:outline-none focus:ring-2 focus:ring-blue-500"
                placeholder="my-org"
              />
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Role
              </label>
              <select
                value={role}
                onChange={(e) => handleRoleChange(e.target.value as UserRole)}
                className="border border-gray-300 rounded px-3 py-2 w-full focus:outline-none focus:ring-2 focus:ring-blue-500"
              >
                <option value="user">User</option>
                <option value="developer">Developer</option>
                <option value="admin">Admin</option>
              </select>
            </div>

            <div className="flex items-center gap-2">
              <input
                type="checkbox"
                id="disabled_toggle"
                checked={disabled}
                onChange={(e) => handleDisabledToggle(e.target.checked)}
                className="w-4 h-4 text-red-600 rounded border-gray-300"
              />
              <label
                htmlFor="disabled_toggle"
                className="text-sm font-medium text-gray-700"
              >
                Disabled
              </label>
            </div>

            {saveError && (
              <p className="text-sm text-red-600 bg-red-50 border border-red-200 rounded px-3 py-2">
                {saveError}
              </p>
            )}
            {saveSuccess && (
              <p className="text-sm text-green-600 bg-green-50 border border-green-200 rounded px-3 py-2">
                Saved successfully.
              </p>
            )}

            <button
              onClick={handleSave}
              disabled={patchMut.isPending}
              className="bg-blue-600 text-white px-4 py-2 rounded hover:bg-blue-700 disabled:opacity-50"
            >
              {patchMut.isPending ? "Saving..." : "Save Changes"}
            </button>
          </div>
        </div>

        {/* Actions panel */}
        <div className="bg-white shadow rounded-lg p-6 h-fit">
          <h2 className="text-base font-semibold text-gray-900 mb-4">
            Actions
          </h2>
          <div className="space-y-3">
            <button
              onClick={() => setPasswordDialog(true)}
              className="w-full text-left px-4 py-2 border border-gray-300 rounded hover:bg-gray-50 text-sm"
            >
              Reset Password
            </button>
            <button
              onClick={() => setDeleteDialog(true)}
              className="w-full text-left px-4 py-2 border border-red-300 text-red-700 rounded hover:bg-red-50 text-sm"
            >
              Delete User
            </button>
          </div>
        </div>
      </div>

      {/* Tabs */}
      <div className="bg-white shadow rounded-lg overflow-hidden">
        <div className="flex gap-4 border-b border-gray-200 px-6">
          <button
            className="py-3 text-sm font-medium border-b-2 border-blue-600 text-blue-600"
          >
            Access
          </button>
        </div>
        <div className="p-6">
          <AccessList userId={numId} />
        </div>
      </div>

      {/* Dialogs */}
      <ConfirmDialog
        open={deleteDialog}
        title="Delete user"
        description={`Permanently delete user "${user.username}"? This action cannot be undone.`}
        confirmLabel="Delete"
        destructive
        onConfirm={handleDelete}
        onCancel={() => setDeleteDialog(false)}
      />
      <ConfirmDialog
        open={disableConfirmDialog}
        title={pendingDisabled ? "Disable user" : "Enable user"}
        description={
          pendingDisabled
            ? `This will immediately log out "${user.username}" and revoke all their sessions.`
            : `Re-enable "${user.username}" account?`
        }
        confirmLabel={pendingDisabled ? "Disable" : "Enable"}
        destructive={pendingDisabled ?? false}
        onConfirm={confirmDisabledChange}
        onCancel={() => {
          setDisableConfirmDialog(false);
          setPendingDisabled(null);
        }}
      />
      <ConfirmDialog
        open={roleConfirmDialog}
        title="Change role"
        description={
          pendingRole && !roleAtLeast(pendingRole, role)
            ? `Lower "${user.username}" role to ${pendingRole}? This will immediately log them out.`
            : `Change "${user.username}" role to ${pendingRole ?? role}?`
        }
        confirmLabel="Change role"
        destructive={pendingRole !== null && !roleAtLeast(pendingRole, role)}
        onConfirm={confirmRoleChange}
        onCancel={() => {
          setRoleConfirmDialog(false);
          setPendingRole(null);
        }}
      />

      {/* Password Reset Dialog */}
      {passwordDialog && (
        <div className="fixed inset-0 z-50 flex items-center justify-center">
          <div
            className="absolute inset-0 bg-black/50"
            onClick={() => setPasswordDialog(false)}
          />
          <div className="relative bg-white rounded-lg shadow-xl p-6 max-w-md w-full mx-4 z-10">
            <h2 className="text-lg font-semibold text-gray-900 mb-4">
              Reset Password for {user.username}
            </h2>
            <p className="text-sm text-amber-600 mb-4">
              This will revoke all sessions for this user. They will be required
              to log in again.
            </p>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                New Password
              </label>
              <input
                type="password"
                value={newPassword}
                onChange={(e) => setNewPassword(e.target.value)}
                className="border border-gray-300 rounded px-3 py-2 w-full focus:outline-none focus:ring-2 focus:ring-blue-500"
                placeholder="Min 12 characters"
                autoComplete="new-password"
              />
              {passwordError && (
                <p className="text-xs text-red-600 mt-1">{passwordError}</p>
              )}
            </div>
            <div className="flex justify-end gap-3 mt-6">
              <button
                onClick={() => {
                  setPasswordDialog(false);
                  setNewPassword("");
                  setPasswordError(null);
                }}
                className="px-4 py-2 rounded border border-gray-300 text-sm hover:bg-gray-50"
              >
                Cancel
              </button>
              <button
                onClick={handlePasswordReset}
                disabled={changePasswordMut.isPending}
                className="bg-blue-600 text-white px-4 py-2 rounded hover:bg-blue-700 disabled:opacity-50 text-sm"
              >
                {changePasswordMut.isPending ? "Resetting..." : "Reset"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
