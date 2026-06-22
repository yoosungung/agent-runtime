import { vfsPathSegments } from "../lib/vfsPaths";

interface Props {
  path: string;
  onNavigate: (path: string) => void;
}

export function VfsBreadcrumbs({ path, onNavigate }: Props) {
  const breadcrumbs = vfsPathSegments(path);
  return (
    <div className="mb-4 flex flex-wrap items-center gap-2 text-sm text-gray-600">
      {breadcrumbs.map((crumb, idx) => (
        <span key={crumb.path} className="inline-flex items-center gap-2">
          {idx > 0 && <span>/</span>}
          <button
            type="button"
            className={`hover:text-blue-600 ${crumb.path === path ? "font-semibold text-gray-900" : ""}`}
            onClick={() => onNavigate(crumb.path)}
          >
            {crumb.label}
          </button>
        </span>
      ))}
    </div>
  );
}
