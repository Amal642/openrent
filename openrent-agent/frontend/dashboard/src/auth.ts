import { apiRequest } from "@/api/client";

const TOKEN_KEY = "land-royal-crm-token";
const AUTH_EVENT = "land-royal-auth-change";

export type AuthUser = {
  username: string;
};

export type LoginResponse = AuthUser & {
  token: string;
  expires_in: number;
};

export function getAuthToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function setAuthToken(token: string) {
  localStorage.setItem(TOKEN_KEY, token);
  window.dispatchEvent(new Event(AUTH_EVENT));
}

export function clearAuthToken() {
  localStorage.removeItem(TOKEN_KEY);
  window.dispatchEvent(new Event(AUTH_EVENT));
}

export function subscribeToAuthChanges(listener: () => void) {
  window.addEventListener(AUTH_EVENT, listener);
  window.addEventListener("storage", listener);
  return () => {
    window.removeEventListener(AUTH_EVENT, listener);
    window.removeEventListener("storage", listener);
  };
}

export function login(username: string, password: string): Promise<LoginResponse> {
  return apiRequest<LoginResponse>("/auth/login", {
    method: "POST",
    body: JSON.stringify({ username, password }),
  });
}

export function getCurrentUser(): Promise<AuthUser> {
  return apiRequest<AuthUser>("/auth/me");
}

export function loginUrl(reason?: "expired") {
  const next = `${window.location.pathname}${window.location.search}${window.location.hash}`;
  const search = new URLSearchParams();
  if (next !== "/login" && next.startsWith("/") && !next.startsWith("//")) {
    search.set("next", next);
  }
  if (reason) search.set("reason", reason);
  return `/login${search.size ? `?${search.toString()}` : ""}`;
}

export function logout(reason?: "expired") {
  clearAuthToken();
  window.location.replace(loginUrl(reason));
}
