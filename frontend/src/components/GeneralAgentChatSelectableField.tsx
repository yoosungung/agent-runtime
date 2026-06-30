interface GeneralAgentChatSelectableFieldProps {
  checked: boolean;
  onChange: (checked: boolean) => void;
}

export function GeneralAgentChatSelectableField({
  checked,
  onChange,
}: GeneralAgentChatSelectableFieldProps) {
  return (
    <label className="flex items-start gap-2 text-sm text-gray-700">
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        className="mt-0.5"
      />
      <span>
        <span className="font-medium">Chat에서 선택 가능</span>
        <span className="block text-xs text-gray-500 mt-0.5">
          해제하면 Chat picker에는 보이지 않지만, 다른 agent의 delegate 대상으로는 호출될 수
          있습니다 (ACL이 있을 때).
        </span>
      </span>
    </label>
  );
}
