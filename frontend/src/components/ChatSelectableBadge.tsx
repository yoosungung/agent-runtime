interface Props {
  selectable: boolean | undefined;
}

export function ChatSelectableBadge({ selectable }: Props) {
  const enabled = selectable ?? true;
  return (
    <span
      className={`text-xs font-medium px-2 py-0.5 rounded ${
        enabled
          ? "bg-green-100 text-green-800"
          : "bg-gray-100 text-gray-600"
      }`}
    >
      {enabled ? "Yes" : "No"}
    </span>
  );
}
