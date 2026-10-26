// API client. The access token lives in memory only (never localStorage, TH-02); the refresh
// token is an HttpOnly cookie scoped to /api/v1/auth that this code never sees.

import type { User } from "./types";

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public details: { field: string; issue: string }[] = [],
    public requestId: string | null = null,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export interface TokenResponse {
  access_token: string;
  token_type: "bearer";
  expires_in: number;
  user: User;
}

let accessToken: string | null = null;
let refreshing: Promise<TokenResponse | null> | null = null;
let onAuthLost: (() => void) | null = null;

export function setAccessToken(token: string | null): void {
  accessToken = token;
}

export function getAccessToken(): string | null {
  return accessToken;
}

export function setAuthLostHandler(handler: (() => void) | null): void {
  onAuthLost = handler;
}

const BASE = "/api/v1";
const CSRF = { "X-Requested-With": "toolkit-web" };

type Query = Record<string, string | number | boolean | null | undefined | (string | number)[]>;

export function buildQuery(query?: Query): string {
  if (!query) return "";
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value === undefined || value === null || value === "") continue;
    if (Array.isArray(value)) value.forEach((v) => params.append(key, String(v)));
    else params.append(key, String(value));
  }
  const s = params.toString();
  return s ? `?${s}` : "";
}

async function parseError(res: Response): Promise<ApiError> {
  let body: unknown = null;
  try {
    body = await res.json();
  } catch {
    body = null;
  }
  const err = (body as { error?: { code?: string; message?: string; details?: { field: string; issue: string }[];
    request_id?: string } } | null)?.error;
  return new ApiError(
    res.status,
    err?.code ?? (res.status >= 500 ? "UPSTREAM_ERROR" : "BAD_REQUEST"),
    err?.message ?? `Request failed (${res.status}).`,
    err?.details ?? [],
    err?.request_id ?? res.headers.get("X-Request-ID"),
  );
}

export async function refreshSession(): Promise<TokenResponse | null> {
  if (!refreshing) {
    refreshing = (async () => {
      try {
        const res = await fetch(`${BASE}/auth/refresh`, { method: "POST", credentials: "same-origin", headers: CSRF });
        if (!res.ok) return null;
        const data = (await res.json()) as TokenResponse;
        accessToken = data.access_token;
        return data;
      } catch {
        return null;
      } finally {
        setTimeout(() => {
          refreshing = null;
        }, 0);
      }
    })();
  }
  return refreshing;
}

export interface RequestOptions {
  method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  body?: unknown;
  query?: Query;
  signal?: AbortSignal;
}

export async function api<T>(path: string, opts: RequestOptions = {}, retried = false): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json" };
  if (accessToken) headers.Authorization = `Bearer ${accessToken}`;
  if (opts.body !== undefined) headers["Content-Type"] = "application/json";
  let res: Response;
  try {
    res = await fetch(`${BASE}${path}${buildQuery(opts.query)}`, {
      method: opts.method ?? "GET",
      headers,
      body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
      credentials: "same-origin",
      signal: opts.signal,
    });
  } catch (e) {
    if ((e as Error).name === "AbortError") throw e;
    throw new ApiError(0, "NETWORK_ERROR", "The server could not be reached. Check your connection.");
  }
  if (res.status === 401 && !retried && !path.startsWith("/auth/")) {
    const refreshed = await refreshSession();
    if (refreshed) return api<T>(path, opts, true);
    accessToken = null;
    onAuthLost?.();
  }
  if (!res.ok) throw await parseError(res);
  if (res.status === 204) return null as T;
  const text = await res.text();
  return (text ? JSON.parse(text) : null) as T;
}

export async function login(email: string, password: string): Promise<TokenResponse> {
  const res = await fetch(`${BASE}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
    credentials: "same-origin",
  });
  if (!res.ok) throw await parseError(res);
  const data = (await res.json()) as TokenResponse;
  accessToken = data.access_token;
  return data;
}

export async function logout(): Promise<void> {
  try {
    await fetch(`${BASE}/auth/logout`, {
      method: "POST",
      headers: { ...CSRF, ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}) },
      credentials: "same-origin",
    });
  } finally {
    accessToken = null;
  }
}
