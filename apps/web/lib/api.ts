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
  const data = await response.json();
  if (!response.ok) throw new Error(data.error?.message || "Request failed");
  return data as T;
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
