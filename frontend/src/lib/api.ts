import type { ApiErrorBody, BlastResult, ScanReport, WhyResult } from "./types";

const BASE_URL = (import.meta.env.VITE_API_URL as string | undefined) ?? "http://localhost:8420";

export class ApiError extends Error {
  status: number;
  constructor(status: number, detail: string) {
    super(detail);
    this.status = status;
  }
}

async function request<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`);
  if (!res.ok) {
    const body = (await res.json().catch(() => null)) as ApiErrorBody | null;
    throw new ApiError(res.status, body?.detail ?? res.statusText);
  }
  return res.json() as Promise<T>;
}

export async function getHealth(): Promise<{ status: string }> {
  return request("/health");
}

export interface ScanOptions {
  maxLen?: number;
  offline?: boolean;
}

export async function scanRepo(repoUrl: string, opts: ScanOptions = {}): Promise<ScanReport> {
  const res = await fetch(`${BASE_URL}/scan`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      repo_url: repoUrl,
      max_len: opts.maxLen ?? 12,
      offline: opts.offline ?? false,
    }),
  });
  if (!res.ok) {
    const body = (await res.json().catch(() => null)) as ApiErrorBody | null;
    throw new ApiError(res.status, body?.detail ?? res.statusText);
  }
  return res.json() as Promise<ScanReport>;
}

export async function getBlastRadius(
  spec: string,
  opts: { maxLen?: number; scanId?: string } = {},
): Promise<BlastResult> {
  const params = new URLSearchParams();
  if (opts.maxLen) params.set("max_len", String(opts.maxLen));
  if (opts.scanId) params.set("scan_id", opts.scanId);
  const qs = params.toString();
  return request(`/blast/${encodeURIComponent(spec)}${qs ? `?${qs}` : ""}`);
}

export async function whyReachable(
  source: string,
  target: string,
  opts: { maxLen?: number; scanId?: string } = {},
): Promise<WhyResult> {
  const params = new URLSearchParams({ source, target });
  if (opts.maxLen) params.set("max_len", String(opts.maxLen));
  if (opts.scanId) params.set("scan_id", opts.scanId);
  return request(`/why?${params.toString()}`);
}
