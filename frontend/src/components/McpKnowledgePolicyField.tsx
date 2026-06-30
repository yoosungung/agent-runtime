interface Props {
  checked: boolean;
  onChange: (checked: boolean) => void;
  disabled?: boolean;
}

export function McpKnowledgePolicyField({
  checked,
  onChange,
  disabled = false,
}: Props) {
  return (
    <label className="flex items-center gap-2 text-sm">
      <input
        type="checkbox"
        checked={checked}
        disabled={disabled}
        onChange={(e) => onChange(e.target.checked)}
      />
      <span>Pipeline project binding 필요 (general agent knowledge 경계)</span>
    </label>
  );
}
