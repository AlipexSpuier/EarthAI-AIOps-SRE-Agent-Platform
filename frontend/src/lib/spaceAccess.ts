import type { SpaceModule, User } from '../types';

export function enabledSpaceModules(user: User | null | undefined): SpaceModule[] {
  if (!user) return [];
  if (user.space_modules === undefined) return ['personal'];
  const modules = user.space_modules;
  if (!Array.isArray(modules) || modules.some(module => module !== 'personal' && module !== 'team') || new Set(modules).size !== modules.length) return [];
  return (['personal', 'team'] as const).filter(module => modules.includes(module));
}

export function canUseSpace(user: User | null | undefined, module: SpaceModule): boolean {
  return Boolean(user && user.role !== 'admin' && !user.disabled && !user.must_change_password && enabledSpaceModules(user).includes(module));
}
