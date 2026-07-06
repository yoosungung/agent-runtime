export type ResourceVisibility = "private" | "tenant" | "public" | "allowlist";

/** @deprecated use ResourceVisibility */
export type GeneralVisibility = ResourceVisibility;

export const RESOURCE_ACCESS_OPTIONS: {
  value: ResourceVisibility;
  label: string;
  description: string;
}[] = [
  {
    value: "private",
    label: "나만 허용",
    description: "등록한 본인만 이 리소스를 사용할 수 있습니다.",
  },
  {
    value: "tenant",
    label: "내 tenant 허용",
    description: "같은 tenant 사용자가 사용할 수 있습니다. (계정에 tenant 필요)",
  },
  {
    value: "public",
    label: "모두 허용",
    description: "로그인한 모든 사용자가 사용할 수 있습니다.",
  },
  {
    value: "allowlist",
    label: "지정된 사용자 허용",
    description: "아래 목록에 추가한 사용자만 사용할 수 있습니다.",
  },
];

/** @deprecated use RESOURCE_ACCESS_OPTIONS */
export const GENERAL_VISIBILITY_OPTIONS = RESOURCE_ACCESS_OPTIONS;

export function resourceAccessLabel(
  visibility: ResourceVisibility | string | null | undefined,
): string {
  return (
    RESOURCE_ACCESS_OPTIONS.find((o) => o.value === visibility)?.label ??
    visibility ??
    "-"
  );
}

/** @deprecated use resourceAccessLabel */
export function generalVisibilityLabel(
  visibility: GeneralVisibility | string | null | undefined,
): string {
  return resourceAccessLabel(visibility);
}
