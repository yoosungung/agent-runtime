import type { ReactNode } from "react";

interface Props {
  title?: ReactNode;
  children?: ReactNode;
  className?: string;
}

export function PageHeader({ title, children, className = "" }: Props) {
  return (
    <div
      className={`flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between mb-6 ${className}`}
    >
      {title ? (
        <h1 className="text-xl sm:text-2xl font-bold text-gray-900">{title}</h1>
      ) : (
        <div />
      )}
      {children ? (
        <div className="flex flex-wrap items-center gap-2 shrink-0">{children}</div>
      ) : null}
    </div>
  );
}
