import type { GeneralVisibility } from "../lib/generalVisibility";
import { GENERAL_VISIBILITY_OPTIONS } from "../lib/generalVisibility";
import { useSession } from "../hooks/useSession";
import { formInputClassName } from "./FormPageLayout";

interface Props {
  value: GeneralVisibility;
  onChange: (value: GeneralVisibility) => void;
  disabled?: boolean;
}

export function GeneralAgentVisibilityField({
  value,
  onChange,
  disabled = false,
}: Props) {
  const { data: session } = useSession();
  const hasTenant = Boolean(session?.tenant);
  const selectedOption = GENERAL_VISIBILITY_OPTIONS.find((o) => o.value === value);

  return (
    <div>
      <label
        htmlFor="general-agent-visibility"
        className="block text-sm font-medium text-gray-700 mb-1"
      >
        사용 권한
      </label>
      <select
        id="general-agent-visibility"
        value={value}
        disabled={disabled}
        onChange={(e) => onChange(e.target.value as GeneralVisibility)}
        className={formInputClassName}
      >
        {GENERAL_VISIBILITY_OPTIONS.map((option) => {
          const tenantDisabled =
            option.value === "tenant" && !hasTenant && !disabled;
          return (
            <option
              key={option.value}
              value={option.value}
              disabled={tenantDisabled}
            >
              {option.label}
            </option>
          );
        })}
      </select>
      {selectedOption && (
        <p className="text-xs text-gray-500 mt-1">{selectedOption.description}</p>
      )}
      {!hasTenant && !disabled && (
        <p className="text-xs text-amber-600 mt-1">
          계정에 tenant가 없어 &quot;내 테넌트만 사용&quot;을 선택할 수 없습니다.
        </p>
      )}
    </div>
  );
}
