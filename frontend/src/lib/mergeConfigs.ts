export function mergeConfigs(
  source: Record<string, unknown>,
  user: Record<string, unknown>,
): Record<string, unknown> {
  return { ...source, ...user };
}

export type DiffKey = {
  key: string;
  sourceValue: unknown;
  userValue: unknown;
  state: "source-only" | "user-only" | "overridden";
};

export function getDiffKeys(
  source: Record<string, unknown>,
  user: Record<string, unknown>,
): DiffKey[] {
  const allKeys = new Set([...Object.keys(source), ...Object.keys(user)]);
  return Array.from(allKeys).map((key) => {
    const inSource = key in source;
    const inUser = key in user;
    if (inSource && inUser)
      return {
        key,
        sourceValue: source[key],
        userValue: user[key],
        state: "overridden" as const,
      };
    if (inSource)
      return {
        key,
        sourceValue: source[key],
        userValue: undefined,
        state: "source-only" as const,
      };
    return {
      key,
      sourceValue: undefined,
      userValue: user[key],
      state: "user-only" as const,
    };
  });
}
