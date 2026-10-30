export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string, public fieldErrors?: Record<string, string>, public requestId?: string) { super(message); }
}
export const API_BASE = process.env.NEXT_PUBLIC_DEMO_MODE === '1' ? '/demo-api/v1' : '/api/v1';
export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body && !(init.body instanceof FormData) && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json');
  headers.set('Accept', 'application/json');
  const response = await fetch(API_BASE + path, { ...init, headers, credentials: 'same-origin', cache: 'no-store' });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    if (response.status === 401 && typeof window !== 'undefined' && !path.startsWith('/auth/')) {
      window.dispatchEvent(new Event('sanctum:expired'));
    }
    if (response.status === 403 && typeof window !== 'undefined') window.dispatchEvent(new Event('sanctum:denied'));
    throw new ApiError(response.status, body.code || 'REQUEST_FAILED', body.message || `Request failed (${response.status})`, body.fieldErrors, body.requestId);
  }
  if (response.status === 204) return {} as T;
  return response.json() as Promise<T>;
}
export function post<T>(path: string, body: unknown): Promise<T> { return api<T>(path, { method: 'POST', body: JSON.stringify(body) }); }
export function patch<T>(path: string, body: unknown): Promise<T> { return api<T>(path, { method: 'PATCH', body: JSON.stringify(body) }); }
export function patientPath(id: string) { return `/patients/${encodeURIComponent(id)}`; }
export async function protectedDownload(path: string, filename: string) {
  const response = await fetch(API_BASE + path, { credentials: 'same-origin', cache: 'no-store' });
  if (!response.ok) {
    if (response.status === 401) window.dispatchEvent(new Event('sanctum:expired'));
    if (response.status === 403) window.dispatchEvent(new Event('sanctum:denied'));
    throw new ApiError(response.status, 'DOWNLOAD_FAILED', response.status === 403 ? 'Access denied' : 'Download could not be completed');
  }
  const url = URL.createObjectURL(await response.blob());
  const a = document.createElement('a'); a.href = url; a.download = filename; a.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 60000);
  return true;
}
