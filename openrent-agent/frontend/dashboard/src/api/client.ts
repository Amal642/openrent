export class ApiError extends Error {
  status: number;
  detail?: unknown;

  constructor(message: string, status: number, detail?: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

const rawBaseUrl = import.meta.env.VITE_API_BASE_URL || "/api";

export const API_BASE_URL = rawBaseUrl.replace(/\/+$/, "");

async function parseResponse(response: Response) {
  const contentType = response.headers.get("content-type") || "";
  if (response.status === 204) return undefined;
  if (contentType.includes("application/json")) return response.json();
  return response.text();
}

export async function apiRequest<T>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers: {
      ...(init.body ? { "content-type": "application/json" } : {}),
      ...init.headers,
    },
  });
  const payload = await parseResponse(response);

  if (!response.ok) {
    const detail =
      payload && typeof payload === "object" && "detail" in payload
        ? (payload as { detail: unknown }).detail
        : payload;
    throw new ApiError(
      typeof detail === "string" ? detail : `API request failed with ${response.status}`,
      response.status,
      detail,
    );
  }

  return payload as T;
}

export function get<T>(path: string): Promise<T> {
  return apiRequest<T>(path);
}

export function post<T>(path: string, body?: unknown): Promise<T> {
  return apiRequest<T>(path, {
    method: "POST",
    body: body === undefined ? undefined : JSON.stringify(body),
  });
}

export function patch<T>(path: string, body: unknown): Promise<T> {
  return apiRequest<T>(path, {
    method: "PATCH",
    body: JSON.stringify(body),
  });
}

export function del<T>(path: string): Promise<T> {
  return apiRequest<T>(path, { method: "DELETE" });
}
