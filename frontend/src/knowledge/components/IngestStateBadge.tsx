export function ingestStateClass(state: string): string {
  if (state === "pending") return "bg-yellow-100 text-yellow-800";
  if (state === "indexed_rag") return "bg-green-100 text-green-800";
  if (state === "dead_letter") return "bg-red-100 text-red-800";
  if (state === "purging") return "bg-orange-100 text-orange-800";
  if (state === "purged") return "bg-gray-100 text-gray-600";
  return "bg-gray-100 text-gray-700";
}

export function IngestStateBadge({ state }: { state: string }) {
  return (
    <span
      className={`inline-block px-2 py-0.5 rounded text-xs ${ingestStateClass(state)}`}
    >
      {state}
    </span>
  );
}
