import { createContext, useContext, useEffect, useState } from 'react';
import type { ReactNode } from 'react';
import { api } from '../lib/api';

export interface Branding {
  name: string; subtitle: string; tagline: string; icon_url: string; favicon_url: string;
  title_font_family: string; title_font_size: number; title_color: string;
  subtitle_font_family: string; subtitle_font_size: number; subtitle_color: string;
}
export const defaultBranding: Branding = {
  name: 'EarthAI', subtitle: 'WORKSPACE', tagline: '智能运维 · 可靠执行', icon_url: '', favicon_url: '/favicon.ico',
  title_font_family: 'DM Sans', title_font_size: 23, title_color: '#253c34',
  subtitle_font_family: 'DM Sans', subtitle_font_size: 8, subtitle_color: '#76837b',
};
const BrandingContext = createContext<Branding>(defaultBranding);
export function BrandingProvider({ children }: { children: ReactNode }) {
  const [branding, setBranding] = useState(defaultBranding);
  useEffect(() => {
    let active = true;
    const load = () => { void api.get<Partial<Branding>>('/branding').then(value => { if (active && typeof value.name === 'string') setBranding({ ...defaultBranding, ...value }); }).catch(() => undefined); };
    load(); window.addEventListener('earthai:branding-changed', load);
    return () => { active = false; window.removeEventListener('earthai:branding-changed', load); };
  }, []);
  useEffect(() => {
    document.title = `${branding.name} · ${branding.subtitle}`;
    const icons = document.querySelectorAll<HTMLLinkElement>('link[rel="icon"]');
    icons.forEach(icon => { icon.href = branding.favicon_url || '/favicon.ico'; icon.removeAttribute('type'); icon.removeAttribute('sizes'); });
  }, [branding]);
  return <BrandingContext.Provider value={branding}>{children}</BrandingContext.Provider>;
}
export function useBranding() { return useContext(BrandingContext); }
