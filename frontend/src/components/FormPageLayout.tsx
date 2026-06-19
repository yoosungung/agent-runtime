import type { ReactNode } from "react";

interface FormPageLayoutProps {
  title: string;
  description?: ReactNode;
  children: ReactNode;
}

export function FormPageLayout({
  title,
  description,
  children,
}: FormPageLayoutProps) {
  return (
    <div className="w-full">
      <h1 className="text-xl sm:text-2xl font-bold text-gray-900 mb-2">
        {title}
      </h1>
      {description ? (
        <div className="text-sm text-gray-500 mb-6">{description}</div>
      ) : (
        <div className="mb-6" />
      )}
      <div className="bg-white shadow rounded-lg p-4 sm:p-6 w-full">
        {children}
      </div>
    </div>
  );
}

export function FormActions({ children }: { children: ReactNode }) {
  return (
    <div className="flex flex-col-reverse gap-3 pt-6 mt-6 border-t border-gray-100 sm:flex-row sm:justify-end">
      {children}
    </div>
  );
}

export function FormError({ message }: { message: string }) {
  return (
    <div className="bg-red-50 border border-red-200 rounded p-3 text-sm text-red-700">
      {message}
    </div>
  );
}

export const formInputClassName =
  "w-full border border-gray-300 rounded px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500";

export const formPrimaryButtonClassName =
  "bg-blue-600 text-white px-4 py-2 rounded hover:bg-blue-700 text-sm font-medium disabled:opacity-50";

export const formSecondaryButtonClassName =
  "px-4 py-2 rounded border border-gray-300 text-sm hover:bg-gray-50";
