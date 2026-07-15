"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { apiFetch, clearAuthSession, getAuthToken, getStoredUser, setAuthSession, type AuthUser } from "./api-client";

type AuthContextValue = {
  user: AuthUser | null;
  loading: boolean;
  can: (permission: string) => boolean;
  refresh: () => Promise<void>;
};

const PUBLIC_PATHS = new Set(["/login", "/register", "/forgot-password", "/reset-password", "/auth/callback"]);
const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const [user, setUser] = useState<AuthUser | null>(() => getStoredUser());
  const [loading, setLoading] = useState(!PUBLIC_PATHS.has(pathname));

  const refresh = useCallback(async () => {
    const token = getAuthToken();
    if (!token) {
      setUser(null);
      setLoading(false);
      if (!PUBLIC_PATHS.has(pathname)) router.replace("/login");
      return;
    }
    try {
      const current = await apiFetch<AuthUser>("/api/auth/me");
      setUser(current);
      setAuthSession(token, current);
    } catch {
      clearAuthSession();
      setUser(null);
      if (!PUBLIC_PATHS.has(pathname)) router.replace("/login");
    } finally {
      setLoading(false);
    }
  }, [pathname, router]);

  useEffect(() => {
    if (PUBLIC_PATHS.has(pathname)) {
      return;
    }
    const timer = window.setTimeout(() => void refresh(), 0);
    return () => window.clearTimeout(timer);
  }, [pathname, refresh]);

  const value = useMemo<AuthContextValue>(() => ({
    user,
    loading,
    can: (permission) => Boolean(user?.permissions?.includes(permission)),
    refresh,
  }), [loading, refresh, user]);

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const value = useContext(AuthContext);
  if (!value) throw new Error("useAuth must be used inside AuthProvider");
  return value;
}

export function Can({ permission, children }: { permission: string; children: React.ReactNode }) {
  const { can } = useAuth();
  return can(permission) ? <>{children}</> : null;
}
