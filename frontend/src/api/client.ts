const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL ?? "").replace(/\/$/, "");

export class ApiError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

async function responseError(response: Response, fallback: string) {
  const contentType = response.headers.get("content-type") ?? "";

  if (contentType.includes("application/json")) {
    const payload = await response.json().catch(() => null);
    return payload?.detail ?? fallback;
  }

  const text = await response.text().catch(() => "");
  return text || fallback;
}

function apiUrl(path: string) {
  return `${API_BASE_URL}${path.startsWith("/") ? path : `/${path}`}`;
}

export async function requestJson<T>(path: string, init: RequestInit = {}, fallback = "Request failed.") {
  const response = await fetch(apiUrl(path), init);

  if (!response.ok) {
    throw new ApiError(await responseError(response, `${fallback} HTTP ${response.status}.`), response.status);
  }

  if (response.status === 204) {
    return undefined as T;
  }

  return (await response.json()) as T;
}

export async function requestBlob(path: string, init: RequestInit = {}, fallback = "Download failed.") {
  const response = await fetch(apiUrl(path), init);

  if (!response.ok) {
    throw new ApiError(await responseError(response, `${fallback} HTTP ${response.status}.`), response.status);
  }

  return response.blob();
}

export async function postJson<T>(path: string, body: unknown, fallback = "Request failed.") {
  return requestJson<T>(
    path,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    },
    fallback,
  );
}

export async function postForm<T>(path: string, body: FormData, fallback = "Upload failed.") {
  return requestJson<T>(
    path,
    {
      method: "POST",
      body,
    },
    fallback,
  );
}

export async function postBlob(path: string, body: unknown, fallback = "Download failed.") {
  return requestBlob(
    path,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    },
    fallback,
  );
}
