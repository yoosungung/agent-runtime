function getCsrfToken(): string {
  const match = document.cookie.match(/csrf_token=([^;]+)/);
  return match ? decodeURIComponent(match[1]) : "";
}

export async function apiFetch(path: string, init?: RequestInit): Promise<Response> {
  const method = (init?.method ?? "GET").toUpperCase();
  const stateChanging = ["POST", "PUT", "DELETE", "PATCH"].includes(method);

  const headers: Record<string, string> = {
    ...(init?.headers as Record<string, string>),
  };
  if (stateChanging) {
    headers["X-CSRF-Token"] = getCsrfToken();
  }
  if (!(init?.body instanceof FormData)) {
    headers["Content-Type"] = "application/json";
  }

  const resp = await fetch(path, {
    ...init,
    credentials: "include",
    headers,
  });

  if (resp.status === 401) {
    window.location.href = "/login";
    throw new Error("Unauthorized");
  }

  return resp;
}

export async function apiJson<T>(path: string, init?: RequestInit): Promise<T> {
  const resp = await apiFetch(path, init);
  if (!resp.ok) {
    const body = await resp.json().catch(() => ({}));
    throw Object.assign(new Error(body?.detail ?? `HTTP ${resp.status}`), {
      status: resp.status,
      body,
    });
  }
  if (resp.status === 204 || resp.headers.get("content-length") === "0") {
    return undefined as T;
  }
  return resp.json();
}

export interface PageResponse<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}
