import type { ControlLevel, User } from '../types';

const controlLevels: ControlLevel[] = ['observe', 'approve', 'autonomous'];

export function allowedControlLevels(user: User | null | undefined): ControlLevel[] {
  if (!user) return [];
  if (user.role === 'admin' || user.allowed_control_levels === undefined) return [...controlLevels];
  const grants = user.allowed_control_levels;
  if (!Array.isArray(grants) || !grants.length || grants.some(level => !controlLevels.includes(level)) || new Set(grants).size !== grants.length) return [];
  return controlLevels.filter(level => grants.includes(level));
}

export function canUseControl(user: User | null | undefined, level: unknown): level is ControlLevel {
  return allowedControlLevels(user).includes(level as ControlLevel);
}

export function fallbackControl(user: User | null | undefined, preferred?: ControlLevel | null): ControlLevel | undefined {
  const allowed = allowedControlLevels(user);
  if (preferred && allowed.includes(preferred)) return preferred;
  return allowed.includes('observe') ? 'observe' : allowed[0];
}
