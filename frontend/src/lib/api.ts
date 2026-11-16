export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) { super(message); this.name = 'ApiError'; this.status = status; }
}

const inFlightGets = new Map<string, Promise<unknown>>();
let sessionGeneration = 0;

function invalidateGets(): void {
  sessionGeneration += 1;
  inFlightGets.clear();
}

function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const method = (options.method ?? 'GET').toUpperCase();
  const isWrite = method !== 'GET' && method !== 'HEAD';
  const share = Object.keys(options).length === 0;
  if (isWrite) invalidateGets();
  const key = `${sessionGeneration}:${path}`;
  const existing = share ? inFlightGets.get(key) : undefined;
  if (existing) return existing as Promise<T>;

  const pending = fetchRequest<T>(path, options).finally(() => {
    if (isWrite) invalidateGets();
    if (inFlightGets.get(key) === pending) inFlightGets.delete(key);
  });
  if (share) inFlightGets.set(key, pending);
  return pending;
}

async function fetchRequest<T>(path: string, options: RequestInit): Promise<T> {
  const response = await fetch(`/api${path}`, {
    ...options,
    credentials: 'same-origin',
    headers: { ...(options.body && !(options.body instanceof FormData) ? { 'Content-Type': 'application/json' } : {}), ...options.headers },
  });
  if (!response.ok) {
    const body: unknown = await response.json().catch(() => null);
    let message = `请求失败（${response.status}）`;
    if (body && typeof body === 'object' && 'detail' in body) {
      const detail = (body as { detail: unknown }).detail;
      message = typeof detail === 'string' ? detail : Array.isArray(detail)
        ? detail.map((item: { msg?: string; loc?: unknown[] }) => `${item.loc?.slice(1).join('.') || '输入'}：${item.msg || '格式有误'}`).join('；')
        : message;
    }
    if (response.status === 401 && path !== '/auth/me' && !path.startsWith('/auth/login') && !path.startsWith('/auth/register')) {
      window.dispatchEvent(new Event('earthai:unauthorized'));
    }
    if (response.status === 403 && path !== '/auth/me') window.dispatchEvent(new Event('earthai:permissions-refresh'));
    throw new ApiError(message, response.status);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body?: unknown) => request<T>(path, { method: 'POST', body: body === undefined ? undefined : JSON.stringify(body) }),
  patch: <T>(path: string, body: unknown) => request<T>(path, { method: 'PATCH', body: JSON.stringify(body) }),
  delete: (path: string) => request<{ ok: boolean }>(path, { method: 'DELETE' }),
  upload: <T>(path: string, file: File) => { const body = new FormData(); body.append('file', file); return request<T>(path, { method: 'POST', body }); },
};

export function errorMessage(error: unknown): string { return error instanceof Error ? error.message : '操作失败，请稍后重试'; }

export async function downloadFile(id: string, name: string): Promise<void> {
  const response = await fetch(`/api/files/${encodeURIComponent(id)}/download`, { credentials: 'same-origin' });
  if (!response.ok) {
    const data = await response.json().catch(() => ({})) as { detail?: string };
    throw new ApiError(data.detail || '下载失败，请确认文件仍然存在且有访问权限', response.status);
  }
  const url = URL.createObjectURL(await response.blob());
  const anchor = document.createElement('a');
  anchor.href = url; anchor.download = name; document.body.appendChild(anchor); anchor.click(); anchor.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}
