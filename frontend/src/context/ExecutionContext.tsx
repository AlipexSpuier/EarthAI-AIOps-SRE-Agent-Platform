import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { api, errorMessage } from '../lib/api';
import { dataChanged } from '../lib/hooks';
import { isActive } from '../lib/format';
import { useAuth } from './AuthContext';
import { applyRunEvents, mergeApprovals, mergeEvents } from '../lib/runEvents';
import type { Approval, Run, RunDetail, RunEvent } from '../types';

export interface ExecutionSnapshot extends RunDetail { connection: 'connecting' | 'live' | 'reconnecting' | 'closed'; connectionError?: string }
interface ExecutionState {
  runs: Record<string, ExecutionSnapshot>; loading: boolean; error: string;
  watch: (id: string) => Promise<void>; register: (run: Run) => Promise<void>;
  cancel: (id: string) => Promise<void>; decide: (approval: Approval, approved: boolean) => Promise<void>; refresh: () => Promise<void>;
}
const ExecutionContext = createContext<ExecutionState | null>(null);
export function ExecutionProvider({ children }: { children: ReactNode }) {
  const { user } = useAuth();
  const [runs, setRuns] = useState<Record<string, ExecutionSnapshot>>({});
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const store = useRef<Record<string, ExecutionSnapshot>>({});
  const streams = useRef(new Map<string, EventSource>());
  const requests = useRef(new Map<string, Promise<void>>());
  const session = useRef(0);
  const watchRef = useRef<(id: string) => Promise<void>>(async () => undefined);
  const publish = useCallback((id: string, next: ExecutionSnapshot) => { store.current = { ...store.current, [id]: next }; setRuns(store.current); }, []);
  const close = useCallback((id: string) => { streams.current.get(id)?.close(); streams.current.delete(id); }, []);
  const connect = useCallback((id: string) => {
    const snapshot = store.current[id];
    if (!snapshot || !isActive(snapshot.run.status) || streams.current.has(id)) return;
    const after = snapshot.events.reduce((max, event) => Math.max(max, event.id), 0);
    const source = new EventSource(`/api/runs/${encodeURIComponent(id)}/events?after=${after}`, { withCredentials: true });
    streams.current.set(id, source);
    publish(id, { ...snapshot, connection: 'connecting', connectionError: undefined });
    source.onopen = () => { const current = store.current[id]; if (current) publish(id, { ...current, connection: 'live', connectionError: undefined }); };
    source.onmessage = message => {
      let event: RunEvent;
      try { event = JSON.parse(message.data) as RunEvent; } catch { return; }
      const current = store.current[id];
      if (!current || !event || event.run_id !== id || !Number.isFinite(Number(event.id))) return;
      event.id = Number(event.id);
      if (current.events.some(item => item.id === event.id)) return;
      const events = mergeEvents(current.events, [event]);
      const run = applyRunEvents(current.run, [event]);
      const approvals = mergeApprovals(current.approvals, [], [event], run.status);
      publish(id, { ...current, run, events, approvals, connection: isActive(run.status) ? 'live' : 'closed' });
      if (!isActive(run.status) || event.type === 'done') { close(id); void watchRef.current(id); dataChanged(); }
      else if (event.type === 'approval') void watchRef.current(id);
    };
    source.onerror = () => {
      const current = store.current[id];
      if (current && isActive(current.run.status)) {
        publish(id, { ...current, connection: 'reconnecting', connectionError: '连接暂时中断，正在自动重连；后台任务不会因此停止。' });
        if (source.readyState === EventSource.CLOSED) close(id);
        void watchRef.current(id);
      }
    };
  }, [close, publish]);
  const watch = useCallback(async (id: string) => {
    const existing = requests.current.get(id); if (existing) return existing;
    const generation = session.current;
    const request = (async () => {
      try {
        const detail = await api.get<RunDetail>(`/runs/${encodeURIComponent(id)}`);
        if (generation !== session.current) return;
        const current = store.current[id];
        const events = mergeEvents(detail.events || [], current?.events || []);
        const baseRun = current && Date.parse(current.run.updated_at) > Date.parse(detail.run.updated_at) ? current.run : detail.run;
        const run = applyRunEvents(baseRun, events);
        const approvals = mergeApprovals(current?.approvals || [], detail.approvals || [], events, run.status);
        publish(id, { ...detail, run, events, approvals, connection: isActive(run.status) ? current?.connection || 'connecting' : 'closed' });
        if (isActive(run.status)) connect(id); else close(id);
      } catch (err) {
        if (generation !== session.current) return;
        const current = store.current[id];
        if (current) publish(id, { ...current, connectionError: errorMessage(err) });
        else setError(errorMessage(err));
        throw err;
      } finally { if (generation === session.current) requests.current.delete(id); }
    })();
    requests.current.set(id, request); return request;
  }, [publish, connect, close]);
  useEffect(() => { watchRef.current = id => watch(id).catch(() => undefined); }, [watch]);
  const register = useCallback(async (run: Run) => {
    const current = store.current[run.id];
    publish(run.id, current ? { ...current, run } : { run, events: [], approvals: [], connection: isActive(run.status) ? 'connecting' : 'closed' });
    await watch(run.id);
  }, [publish, watch]);
  const refresh = useCallback(async () => {
    if (!user) return;
    const generation = session.current;
    setLoading(true); setError('');
    try {
      const list = await api.get<Run[]>('/runs');
      if (generation !== session.current) return;
      await Promise.all(list.filter(run => isActive(run.status) || (store.current[run.id] && isActive(store.current[run.id].run.status))).map(run => (store.current[run.id] ? watch(run.id) : register(run)).catch(() => undefined)));
    } catch (err) { if (generation === session.current) setError(errorMessage(err)); }
    finally { if (generation === session.current) setLoading(false); }
  }, [user?.id, register, watch]);
  useEffect(() => {
    session.current++; store.current = {}; setRuns({}); requests.current.clear();
    streams.current.forEach(source => source.close()); streams.current.clear();
    if (user) void refresh();
    return () => { session.current++; streams.current.forEach(source => source.close()); streams.current.clear(); };
  }, [user?.id, refresh]);
  useEffect(() => {
    if (!user) return;
    const timer = window.setInterval(() => { void refresh(); }, 15000);
    const onFocus = () => { void refresh(); };
    window.addEventListener('focus', onFocus);
    return () => { window.clearInterval(timer); window.removeEventListener('focus', onFocus); };
  }, [user?.id, refresh]);
  const cancel = async (id: string) => {
    const run = await api.post<Run>(`/runs/${id}/cancel`); const current = store.current[id];
    if (current) publish(id, { ...current, run, connection: isActive(run.status) ? current.connection : 'closed' });
    if (!isActive(run.status)) close(id);
    await watch(id); dataChanged();
  };
  const decide = async (approval: Approval, approved: boolean) => {
    const updated = await api.post<Approval>(`/approvals/${approval.id}`, { approved });
    const current = store.current[approval.run_id];
    if (current) publish(approval.run_id, { ...current, approvals: current.approvals.map(item => item.id === updated.id ? updated : item) });
    await watch(approval.run_id); dataChanged();
  };
  return <ExecutionContext.Provider value={{ runs, loading, error, watch, register, cancel, decide, refresh }}>{children}</ExecutionContext.Provider>;
}
export function useExecutions() { const context = useContext(ExecutionContext); if (!context) throw new Error('ExecutionProvider is required'); return context; }
