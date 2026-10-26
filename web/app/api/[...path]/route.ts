// Same-origin proxy to the API (runtime-configurable via API_BASE_URL). Keeps the refresh cookie
// first-party, avoids CORS, and means the browser never talks to any other origin (CON-07).
//   /api/v1/...      → ${API_BASE_URL}/api/v1/...
//   /api/health|ready → ${API_BASE_URL}/health|ready

import type { NextRequest } from "next/server";

export const dynamic = "force-dynamic";

const HOP_BY_HOP = new Set([
  "connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te", "trailer", "transfer-encoding",
  "upgrade", "host", "content-length", "accept-encoding",
]);
const STRIP_RESPONSE = new Set([...HOP_BY_HOP, "content-encoding"]);

function target(path: string[], search: string): string | null {
  const base = (process.env.API_BASE_URL ?? "http://localhost:8000").replace(/\/$/, "");
  if (path.some((p) => p === ".." || p === "." || p.includes("\\"))) return null;
  if (path.length === 1 && (path[0] === "health" || path[0] === "ready")) return `${base}/${path[0]}`;
  if (path[0] !== "v1") return null;
  return `${base}/api/${path.map(encodeURIComponent).join("/")}${search}`;
}

async function proxy(req: NextRequest, ctx: { params: Promise<{ path: string[] }> }): Promise<Response> {
  const { path } = await ctx.params;
  const url = target(path, req.nextUrl.search);
  if (!url) return Response.json({ error: { code: "NOT_FOUND", message: "Not found.", details: [] } }, { status: 404 });
  const headers = new Headers();
  req.headers.forEach((value, key) => {
    if (!HOP_BY_HOP.has(key.toLowerCase())) headers.set(key, value);
  });
  const forwarded = req.headers.get("x-forwarded-for");
  const ip = forwarded?.split(",")[0]?.trim() ?? "";
  if (ip) headers.set("x-forwarded-for", ip);
  const init: RequestInit & { duplex?: string } = {
    method: req.method,
    headers,
    redirect: "manual",
    cache: "no-store",
  };
  if (req.method !== "GET" && req.method !== "HEAD") {
    init.body = await req.arrayBuffer();
  }
  let upstream: Response;
  try {
    upstream = await fetch(url, init);
  } catch {
    return Response.json(
      { error: { code: "UPSTREAM_ERROR", message: "The API is unreachable.", details: [], request_id: null } },
      { status: 502 },
    );
  }
  const out = new Headers();
  upstream.headers.forEach((value, key) => {
    if (!STRIP_RESPONSE.has(key.toLowerCase()) && key.toLowerCase() !== "set-cookie") out.set(key, value);
  });
  for (const cookie of upstream.headers.getSetCookie()) out.append("set-cookie", cookie);
  return new Response(upstream.status === 204 ? null : await upstream.arrayBuffer(), { status: upstream.status, headers: out });
}

export const GET = proxy;
export const POST = proxy;
export const PUT = proxy;
export const PATCH = proxy;
export const DELETE = proxy;
