import { createContext, useCallback, useContext, useEffect, useState } from 'react';
import type { ReactNode } from 'react';
import { api, errorMessage } from '../lib/api';
import { useAuth } from './AuthContext';
import type { Catalog } from '../types';

const emptyCatalog: Catalog = { servers: [], providers: [], agents: [], projects: [], knowledge: [], skills: [] };
interface CatalogState extends Catalog { loading: boolean; error: string; reload: () => Promise<void> }
const CatalogContext = createContext<CatalogState>({ ...emptyCatalog, loading: true, error: '', reload: async () => undefined });
export function CatalogProvider({ children }: { children: ReactNode }) {
  const { user } = useAuth();
  const [catalog, setCatalog] = useState<Catalog>(emptyCatalog);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const reload = useCallback(async () => {
    if (!user) return;
    const keys = Object.keys(emptyCatalog) as (keyof Catalog)[];
    const results = await Promise.allSettled(keys.map(key => api.get<Catalog[typeof key]>(`/${key}`)));
    const next: Partial<Catalog> = {}; const failures: string[] = [];
    results.forEach((result, i) => { if (result.status === 'fulfilled') Object.assign(next, { [keys[i]]: result.value }); else failures.push(errorMessage(result.reason)); });
    setCatalog(current => ({ ...current, ...next })); setError(failures[0] || ''); setLoading(false);
  }, [user?.id]);
  useEffect(() => { if (user) { void reload(); } else { setCatalog(emptyCatalog); setLoading(false); } }, [user?.id, reload]);
  useEffect(() => { const refresh = () => { void reload(); }; window.addEventListener('earthai:data-changed', refresh); return () => window.removeEventListener('earthai:data-changed', refresh); }, [reload]);
  return <CatalogContext.Provider value={{ ...catalog, loading, error, reload }}>{children}</CatalogContext.Provider>;
}
export const useCatalog = () => useContext(CatalogContext);
