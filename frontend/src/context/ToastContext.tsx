import { createContext, useCallback, useContext, useEffect, useState } from 'react';
import type { ReactNode } from 'react';
import { CheckCircle2, CircleAlert, Info, X } from 'lucide-react';

interface Toast { id: number; message: string; kind: 'success' | 'error' | 'info' }
type Notify = (message: string, kind?: Toast['kind']) => void;
const ToastContext = createContext<Notify>(() => undefined);
export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const dismiss = useCallback((id: number) => setToasts(current => current.filter(item => item.id !== id)), []);
  const notify = useCallback<Notify>((message, kind = 'success') => {
    const id = Date.now() + Math.random();
    setToasts(current => [...current.slice(-3), { id, message, kind }]);
  }, []);
  return <ToastContext.Provider value={notify}>{children}<div className="toast-stack" aria-live="polite">{toasts.map(toast => <ToastItem key={toast.id} toast={toast} dismiss={dismiss} />)}</div></ToastContext.Provider>;
}
function ToastItem({ toast, dismiss }: { toast: Toast; dismiss: (id: number) => void }) {
  useEffect(() => { const timer = window.setTimeout(() => dismiss(toast.id), toast.kind === 'error' ? 8000 : 4500); return () => window.clearTimeout(timer); }, [toast.id, toast.kind, dismiss]);
  const Icon = toast.kind === 'error' ? CircleAlert : toast.kind === 'success' ? CheckCircle2 : Info;
  return <div className={`toast ${toast.kind}`}><Icon size={19} /><span>{toast.message}</span><button className="icon-button" onClick={() => dismiss(toast.id)} aria-label="关闭提示"><X size={16} /></button></div>;
}
export const useToast = () => useContext(ToastContext);
