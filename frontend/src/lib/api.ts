export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string, public fieldErrors?: Record<string, string>, public requestId?: string) { super(message); }
}
export const API_BASE = process.env.NEXT_PUBLIC_DEMO_MODE === '1' ? '/demo-api/v1' : '/api/v1';
export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body && !(init.body instanceof FormData) && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json');
  headers.set('Accept', 'application/json');
  let response: Response;
  try {
    response = await fetch(API_BASE + path, { ...init, headers, signal: init.signal ? AbortSignal.any([init.signal, AbortSignal.timeout(30000)]) : AbortSignal.timeout(30000), credentials: 'same-origin', cache: 'no-store' });
  } catch (error) {
    if (init.signal?.aborted) throw error;
    throw new ApiError(0, 'CONNECTION_FAILED', 'The server could not be reached. Check your connection and try again.');
  }
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    if (response.status === 401 && typeof window !== 'undefined' && !path.startsWith('/auth/')) {
      window.dispatchEvent(new Event('sanctum:expired'));
    }
    if ([403, 404].includes(response.status) && typeof window !== 'undefined') {
      window.dispatchEvent(new CustomEvent('sanctum:denied', {detail: {path, status: response.status}}));
    }
    if (response.status === 404 && body.message === 'Not Found') {
      throw new ApiError(404, 'FEATURE_UNAVAILABLE', 'This feature is not available on the connected server yet.', undefined, body.requestId);
    }
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
    if ([403, 404].includes(response.status)) window.dispatchEvent(new CustomEvent('sanctum:denied', {detail: {path, status: response.status}}));
    throw new ApiError(response.status, 'DOWNLOAD_FAILED', response.status === 403 ? 'Access denied' : 'Download could not be completed');
  }
  const url = URL.createObjectURL(await response.blob());
  const a = document.createElement('a'); a.href = url; a.download = filename; a.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 60000);
  return true;
}
