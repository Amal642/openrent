import { useEffect, useState } from "react";
import { Outlet, useRouterState } from "@tanstack/react-router";
import type { QueryClient } from "@tanstack/react-query";
import { AppShell } from "@/layouts/app-shell";
import {
  getAuthToken,
  getCurrentUser,
  loginUrl,
  subscribeToAuthChanges,
  type AuthUser,
} from "@/auth";

type AuthState =
  | { status: "checking"; user: null }
  | { status: "anonymous"; user: null }
  | { status: "authenticated"; user: AuthUser };

export function AuthGate({ queryClient }: { queryClient: QueryClient }) {
  const path = useRouterState({ select: (state) => state.location.pathname });
  const [auth, setAuth] = useState<AuthState>({ status: "checking", user: null });

  useEffect(() => {
    let cancelled = false;

    async function checkAuth() {
      if (!getAuthToken()) {
        if (!cancelled) setAuth({ status: "anonymous", user: null });
        return;
      }

      if (!cancelled) setAuth({ status: "checking", user: null });
      try {
        const user = await getCurrentUser();
        if (!cancelled) setAuth({ status: "authenticated", user });
      } catch {
        if (!cancelled) setAuth({ status: "anonymous", user: null });
      }
    }

    void checkAuth();
    const unsubscribe = subscribeToAuthChanges(() => {
      queryClient.clear();
      void checkAuth();
    });
    return () => {
      cancelled = true;
      unsubscribe();
    };
  }, [queryClient]);

  useEffect(() => {
    if (auth.status === "anonymous" && path !== "/login") {
      window.location.replace(loginUrl());
    }
    if (auth.status === "authenticated" && path === "/login") {
      const params = new URLSearchParams(window.location.search);
      const next = params.get("next");
      window.location.replace(next?.startsWith("/") && !next.startsWith("//") ? next : "/");
    }
  }, [auth.status, path]);

  if (auth.status === "checking") {
    return (
      <div className="flex min-h-screen items-center justify-center bg-background px-4">
        <div className="text-center">
          <div className="mx-auto size-8 animate-spin rounded-full border-2 border-primary border-t-transparent" />
          <p className="mt-3 text-sm text-muted-foreground">Checking your session...</p>
        </div>
      </div>
    );
  }

  if (path === "/login") {
    return <Outlet />;
  }

  if (auth.status !== "authenticated") {
    return null;
  }

  return <AppShell username={auth.user.username} />;
}
