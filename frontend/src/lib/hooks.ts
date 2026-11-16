import { useCallback, useEffect, useRef, useState } from 'react';
import { api, errorMessage } from './api';

export const dataChanged = () => window.dispatchEvent(new Event('earthai:data-changed'));
export function useResource<T>(path: string | null, initial: T) {
  const [data, setData] = useState<T>(initial);
  const [loading, setLoading] = useState(Boolean(path));
  const [error, setError] = useState('');
  const requestId = useRef(0);
  const reload = useCallback(async (quiet = false) => {
    if (!path) { setLoading(false); return; }
    const id = ++requestId.current;
    if (!quiet) setLoading(true);
    try { const next = await api.get<T>(path); if (id === requestId.current) { setData(next); setError(''); } }
    catch (err) { if (id === requestId.current) setError(errorMessage(err)); }
    finally { if (id === requestId.current) setLoading(false); }
  }, [path]);
  useEffect(() => { void reload(); return () => { requestId.current++; }; }, [reload]);
  useEffect(() => { const refresh = () => { void reload(true); }; window.addEventListener('earthai:data-changed', refresh); return () => window.removeEventListener('earthai:data-changed', refresh); }, [reload]);
  return { data, setData, loading, error, reload };
}
