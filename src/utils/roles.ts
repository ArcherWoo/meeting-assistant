import type { Role } from '@/types';

export type AppSurface = 'chat' | 'agent';

function normalizeSurface(value: string): AppSurface | null {
  if (value === 'chat' || value === 'agent') return value;
  return null;
}

export function getRoleAllowedSurfaces(role?: Pick<Role, 'allowed_surfaces'> | null): AppSurface[] {
  const values = Array.isArray(role?.allowed_surfaces) ? role.allowed_surfaces : [];
  const normalized = values
    .map((value) => normalizeSurface(String(value).trim()))
    .filter((value): value is AppSurface => value !== null);
  return normalized.length > 0 ? Array.from(new Set(normalized)) : ['chat'];
}

export function isRoleAllowedOnSurface(role: Pick<Role, 'allowed_surfaces'> | null | undefined, surface: AppSurface): boolean {
  return getRoleAllowedSurfaces(role).includes(surface);
}

export function filterRolesBySurface(roles: Role[], surface: AppSurface): Role[] {
  return roles.filter((role) => isRoleAllowedOnSurface(role, surface));
}

export function getPreferredRoleForSurface(
  roles: Role[],
  surface: AppSurface,
  preferredRoleId?: string | null,
): Role | undefined {
  const surfaceRoles = filterRolesBySurface(roles, surface);
  if (surfaceRoles.length === 0) return undefined;
  return surfaceRoles.find((role) => role.id === preferredRoleId) ?? surfaceRoles[0];
}
