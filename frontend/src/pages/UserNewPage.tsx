import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { userCreateSchema } from "../lib/schemas";
import { useCreateUser } from "../hooks/useUsers";

type FormValues = z.infer<typeof userCreateSchema>;

export function UserNewPage() {
  const navigate = useNavigate();
  const [globalError, setGlobalError] = useState<string | null>(null);
  const createMut = useCreateUser();

  const {
    register,
    handleSubmit,
    watch,
    formState: { errors, isSubmitting },
  } = useForm<FormValues>({
    resolver: zodResolver(userCreateSchema),
    defaultValues: {
      is_admin: false,
    },
  });

  const password = watch("password") ?? "";

  async function onSubmit(values: FormValues) {
    setGlobalError(null);
    try {
      const user = await createMut.mutateAsync({
        username: values.username,
        password: values.password,
        tenant: values.tenant || undefined,
        is_admin: values.is_admin,
      });
      navigate(`/users/${user.id}`);
    } catch (e: unknown) {
      if ((e as { status?: number })?.status === 409) {
        setGlobalError("Username already exists");
      } else {
        setGlobalError(e instanceof Error ? e.message : "Failed to create user");
      }
    }
  }

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
        <h1 className="text-2xl font-bold text-gray-900">New User</h1>
      </div>

      <div className="bg-white shadow rounded-lg p-6 max-w-lg">
        {globalError && (
          <div className="mb-4 bg-red-50 border border-red-200 rounded px-4 py-3 text-sm text-red-700">
            {globalError}
          </div>
        )}

        <form onSubmit={handleSubmit(onSubmit)} className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Username <span className="text-red-500">*</span>
            </label>
            <input
              {...register("username")}
              className="border border-gray-300 rounded px-3 py-2 w-full focus:outline-none focus:ring-2 focus:ring-blue-500"
              placeholder="john.doe"
              autoComplete="off"
            />
            {errors.username && (
              <p className="text-xs text-red-600 mt-1">
                {errors.username.message}
              </p>
            )}
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Password <span className="text-red-500">*</span>
            </label>
            <input
              {...register("password")}
              type="password"
              className="border border-gray-300 rounded px-3 py-2 w-full focus:outline-none focus:ring-2 focus:ring-blue-500"
              autoComplete="new-password"
            />
            <div className="flex items-center justify-between mt-1">
              {errors.password ? (
                <p className="text-xs text-red-600">{errors.password.message}</p>
              ) : (
                <p className="text-xs text-gray-400">Minimum 12 characters</p>
              )}
              <p
                className={`text-xs ${
                  password.length < 12 ? "text-amber-500" : "text-green-600"
                }`}
              >
                {password.length}/12+
              </p>
            </div>
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Tenant{" "}
              <span className="text-xs font-normal text-gray-400">
                (optional)
              </span>
            </label>
            <input
              {...register("tenant")}
              className="border border-gray-300 rounded px-3 py-2 w-full focus:outline-none focus:ring-2 focus:ring-blue-500"
              placeholder="my-org"
            />
          </div>

          <div className="flex items-center gap-2">
            <input
              {...register("is_admin")}
              type="checkbox"
              id="is_admin"
              className="w-4 h-4 text-blue-600 rounded border-gray-300"
            />
            <label
              htmlFor="is_admin"
              className="text-sm font-medium text-gray-700"
            >
              Admin user
            </label>
          </div>

          <div className="flex gap-3 pt-2">
            <button
              type="submit"
              disabled={isSubmitting || createMut.isPending}
              className="bg-blue-600 text-white px-4 py-2 rounded hover:bg-blue-700 disabled:opacity-50"
            >
              {isSubmitting || createMut.isPending
                ? "Creating..."
                : "Create User"}
            </button>
            <button
              type="button"
              onClick={() => navigate("/users")}
              className="px-4 py-2 rounded border border-gray-300 hover:bg-gray-50"
            >
              Cancel
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
