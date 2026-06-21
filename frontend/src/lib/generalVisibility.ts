export type GeneralVisibility = "private" | "tenant" | "public";

export const GENERAL_VISIBILITY_OPTIONS: {
  value: GeneralVisibility;
  label: string;
  description: string;
}[] = [
  {
    value: "private",
    label: "나만 사용",
    description: "본인만 이 agent를 실행할 수 있습니다.",
  },
  {
    value: "tenant",
    label: "내 테넌트만 사용",
    description: "같은 tenant 사용자가 실행할 수 있습니다. (계정에 tenant 필요)",
  },
  {
    value: "public",
    label: "모두 사용",
    description: "로그인한 모든 사용자가 실행할 수 있습니다.",
  },
];

export function generalVisibilityLabel(
  visibility: GeneralVisibility | string | null | undefined,
): string {
  return (
    GENERAL_VISIBILITY_OPTIONS.find((o) => o.value === visibility)?.label ??
    visibility ??
    "-"
  );
}
