import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { api, ApiError, buildQuery, getAccessToken, login, setAccessToken } from "@/lib/api";

function json(status: number, body: unknown, headers: Record<string, string> = {}) {
  return new Response(body === null ? null : JSON.stringify(body), { status, headers: { "Content-Type": "application/json", ...headers } });
}

describe("api client", () => {
  const fetchMock = vi.fn();
  beforeEach(() => {
    vi.stubGlobal("fetch", fetchMock);
    setAccessToken(null);
  });
  afterEach(() => {
    fetchMock.mockReset();
    vi.unstubAllGlobals();
  });

  it("keeps the access token in memory and sends it as a bearer token", async () => {
    fetchMock.mockResolvedValueOnce(json(200, { access_token: "t1", token_type: "bearer", expires_in: 900, user: {} }));
    await login("a@b.c", "pw-123456789012");
    expect(getAccessToken()).toBe("t1");
    expect(window.localStorage.length).toBe(0);
    fetchMock.mockResolvedValueOnce(json(200, { ok: true }));
    await api("/projects");
    const [, init] = fetchMock.mock.calls[1]!;
    expect((init as RequestInit).headers).toMatchObject({ Authorization: "Bearer t1" });
  });

  it("refreshes once on 401 and retries", async () => {
    setAccessToken("expired");
    fetchMock
      .mockResolvedValueOnce(json(401, { error: { code: "TOKEN_EXPIRED", message: "x" } }))
      .mockResolvedValueOnce(json(200, { access_token: "fresh", token_type: "bearer", expires_in: 900, user: {} }))
      .mockResolvedValueOnce(json(200, { items: [] }));
    const out = await api<{ items: unknown[] }>("/projects");
    expect(out.items).toEqual([]);
    expect(fetchMock.mock.calls[1]![0]).toBe("/api/v1/auth/refresh");
    expect((fetchMock.mock.calls[1]![1] as RequestInit).headers).toMatchObject({ "X-Requested-With": "toolkit-web" });
    expect(getAccessToken()).toBe("fresh");
  });

  it("surfaces the error envelope with request ID", async () => {
    fetchMock.mockResolvedValueOnce(json(409, { error: { code: "ACK_REQUIRED", message: "Tick it", details: [], request_id: "req-1" } }));
    const err = await api("/fix-proposals/x/approve", { method: "POST", body: {} }).catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).code).toBe("ACK_REQUIRED");
    expect((err as ApiError).requestId).toBe("req-1");
  });

  it("reports network failures distinctly", async () => {
    fetchMock.mockRejectedValueOnce(new TypeError("failed"));
    const err = (await api("/projects").catch((e: unknown) => e)) as ApiError;
    expect(err.code).toBe("NETWORK_ERROR");
  });

  it("builds repeated query parameters and drops empty ones", () => {
    expect(buildQuery({ status: ["firing", "acknowledged"], q: "", limit: 5, x: undefined })).toBe(
      "?status=firing&status=acknowledged&limit=5",
    );
  });
});
