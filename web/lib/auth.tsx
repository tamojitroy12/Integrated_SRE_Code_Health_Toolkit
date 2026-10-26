"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";

import * as client from "./api";
import type { Role, User } from "./types";

type Status = "loading" | "authenticated" | "anonymous";

interface AuthState {
  status: Status;
  user: User | null;
  login: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  can: (role: Role) => boolean;
}

const RANK: Record<Role, number> = { viewer: 0, maintainer: 1, admin: 2 };
const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<Status>("loading");
  const [user, setUser] = useState<User | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const schedule = useCallback((expiresIn: number) => {
    // Refresh a minute before the short-lived access token expires.
    const arm = (seconds: number): void => {
      if (timer.current) clearTimeout(timer.current);
      timer.current = setTimeout(async () => {
        const r = await client.refreshSession();
        if (r) {
          setUser(r.user);
          arm(r.expires_in);
        } else {
          setUser(null);
          setStatus("anonymous");
        }
      }, Math.max(15, seconds - 60) * 1000);
    };
    arm(expiresIn);
  }, []);

  useEffect(() => {
    let active = true;
    client.setAuthLostHandler(() => {
      setUser(null);
      setStatus("anonymous");
    });
    client.refreshSession().then((r) => {
      if (!active) return;
      if (r) {
        setUser(r.user);
        setStatus("authenticated");
        schedule(r.expires_in);
      } else {
        setStatus("anonymous");
      }
    });
    return () => {
      active = false;
      client.setAuthLostHandler(null);
      if (timer.current) clearTimeout(timer.current);
    };
  }, [schedule]);

  const login = useCallback(
    async (email: string, password: string) => {
      const r = await client.login(email, password);
      setUser(r.user);
      setStatus("authenticated");
      schedule(r.expires_in);
    },
    [schedule],
  );

  const logout = useCallback(async () => {
    await client.logout();
    if (timer.current) clearTimeout(timer.current);
    setUser(null);
    setStatus("anonymous");
  }, []);

  const value = useMemo<AuthState>(
    () => ({ status, user, login, logout, can: (role: Role) => !!user && RANK[user.role] >= RANK[role] }),
    [status, user, login, logout],
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside AuthProvider");
  return ctx;
}
