import type { components } from "./contracts";
export type Schema = components["schemas"];
export type Me = Schema["Me"];
export type Workspace = Schema["Workspace"];
export type Dataset = Schema["DatasetOut"];
export type Source = Schema["SourceOut"];
export type Member = Schema["MemberOut"];
export type Invitation = Schema["InviteOut"];
export type Audit = Schema["AuditOut"];
export type Institution = Schema["InstitutionOut"];
export type User = Schema["UserOut"];
export type Session = Schema["SessionOut"];
export type Page<T> = {
  items: T[];
  total: number;
  offset: number;
  limit: number;
};
let csrf = "";
export function setCSRF(value: string) {
  csrf = value;
}
function apiErrorMessage(body: unknown): string | null {
  if (!body || typeof body !== "object" || !("error" in body)) return null;
  const error = (body as { error?: { message?: unknown } }).error;
  return error && typeof error.message === "string" ? error.message : null;
}

async function readApiResponse<T>(response: Response): Promise<T> {
  if (response.ok && response.status === 204) return undefined as T;
  const contentType = response.headers.get("content-type")?.toLowerCase() || "";
  if (!contentType.includes("application/json") && !contentType.includes("+json")) {
    throw new Error(
      "PLUTO API is unavailable. Please contact the platform administrator.",
    );
  }

  let data: unknown;
  try {
    data = await response.json();
  } catch {
    throw new Error("PLUTO API returned an invalid response. Please try again later.");
  }

  if (!response.ok) {
    throw new Error(apiErrorMessage(data) || `PLUTO request failed (${response.status}).`);
  }
  return data as T;
}

export async function uploadChunk(path: string, data: Blob): Promise<void> {
  const response = await fetch(`/api/v1${path}`, {
    method: "PUT",
    credentials: "same-origin",
    headers: {
      "Content-Type": "application/octet-stream",
      "X-CSRF-Token": csrf,
    },
    body: data,
  });
  if (!response.ok) await readApiResponse(response);
}
export async function api<T>(
  path: string,
  method = "GET",
  body?: unknown,
): Promise<T> {
  const response = await fetch(`/api/v1${path}`, {
    method,
    credentials: "same-origin",
    cache: "no-store",
    headers: {
      "Content-Type": "application/json",
      ...(csrf ? { "X-CSRF-Token": csrf } : {}),
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  return readApiResponse<T>(response);
}
export async function all<T>(path: string): Promise<T[]> {
  const items: T[] = [];
  let offset = 0;
  for (;;) {
    const result = await api<Page<T>>(`${path}?offset=${offset}&limit=100`);
    items.push(...result.items);
    offset += result.items.length;
    if (offset >= result.total || result.items.length === 0) return items;
  }
}
