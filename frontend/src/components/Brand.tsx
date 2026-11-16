import { Globe2 } from 'lucide-react';
import { defaultBranding, useBranding } from '../context/BrandingContext';
import './Brand.css';

export function Brand({ compact = false }: { compact?: boolean }) {
  const value = useBranding();
  return <span className="system-brand"><span className="brand-mark">{value.icon_url ? <img src={value.icon_url} alt="系统图标" /> : <Globe2 size={24} />}</span><span className="system-brand-title" style={{ fontFamily: value.title_font_family, fontSize: value.title_font_size, color: value.title_color === defaultBranding.title_color ? 'var(--ink)' : value.title_color }}>{value.name}</span>{!compact && <span className="system-brand-subtitle" style={{ fontFamily: value.subtitle_font_family, fontSize: value.subtitle_font_size, color: value.subtitle_color === defaultBranding.subtitle_color ? 'var(--muted-strong)' : value.subtitle_color }}>{value.subtitle}</span>}</span>;
}
