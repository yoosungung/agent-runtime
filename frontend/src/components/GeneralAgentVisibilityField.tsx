import type { GeneralVisibility } from "../lib/generalVisibility";
import {
  GENERAL_VISIBILITY_OPTIONS,
} from "../lib/generalVisibility";
import { useSession } from "../hooks/useSession";

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

  return (
    <fieldset className="space-y-2">
      <legend className="block text-sm font-medium text-gray-700 mb-2">
        사용 권한
      </legend>
      {GENERAL_VISIBILITY_OPTIONS.map((option) => {
        const tenantDisabled =
          option.value === "tenant" && !hasTenant && !disabled;
        return (
          <label
            key={option.value}
            className={`flex items-start gap-3 rounded border p-3 ${
              value === option.value
                ? "border-blue-500 bg-blue-50"
                : "border-gray-200"
            } ${tenantDisabled ? "opacity-60" : ""}`}
          >
            <input
              type="radio"
              name="visibility"
              value={option.value}
              checked={value === option.value}
              disabled={disabled || tenantDisabled}
              onChange={() => onChange(option.value)}
              className="mt-1"
            />
            <span>
              <span className="block text-sm font-medium text-gray-900">
                {option.label}
              </span>
              <span className="block text-xs text-gray-500">
                {option.description}
              </span>
              {tenantDisabled && (
                <span className="block text-xs text-amber-600 mt-1">
                  계정에 tenant가 없어 선택할 수 없습니다.
                </span>
              )}
            </span>
          </label>
        );
      })}
    </fieldset>
  );
}
