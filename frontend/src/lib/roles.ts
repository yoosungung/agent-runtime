export type UserRole = "user" | "developer" | "admin";

const ROLE_RANK: Record<UserRole, number> = {
  user: 0,
  developer: 1,
  admin: 2,
};

export function roleAtLeast(role: UserRole, minimum: UserRole): boolean {
  return ROLE_RANK[role] >= ROLE_RANK[minimum];
}

export function isAdminRole(role: UserRole): boolean {
  return roleAtLeast(role, "admin");
}

export function isDeveloperRole(role: UserRole): boolean {
  return roleAtLeast(role, "developer");
}
