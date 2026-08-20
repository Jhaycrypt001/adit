import type { ApiErrorBody, BlastResult, ScanReport, WhyResult } from "./types";

/**
 * Normalise whatever was put in `VITE_API_URL`.
 *
 * Two mistakes are near-universal when this is typed into a hosting
 * dashboard, and both fail in a way that points at the wrong thing:
 *
 *   `api-x.up.railway.app`    a bare host with no scheme is a *relative* URL
 *                             to `fetch`, so the request goes to
 *                             `your-site.vercel.app/api-x.up.railway.app/...`
 *                             and the console reports the API as unreachable
 *                             while the API is perfectly healthy.
 *   `https://api-x.../`       a trailing slash yields `...//health`, which
 *                             some routers accept and others 404.
 *
 * Neither is worth a support round trip, so both are repaired here. A bare
 * host is assumed https: this app is served over https in every deployment,
 * and a browser blocks plain http from an https page anyway.
 */
function normaliseBaseUrl(raw: string | undefined): string {
  const value = (raw ?? "").trim();
  if (!value) return "http://localhost:8420";

  const withScheme = /^https?:\/\//i.test(value) ? value : `https://${value}`;
  return withScheme.replace(/\/+$/, "");
}

const BASE_URL = normaliseBaseUrl(import.meta.env.VITE_API_URL as string | undefined);

export const API_BASE_URL = BASE_URL;

export class ApiError extends Error {
  status: number;
  /** Present when the failure was transport-level rather than an HTTP status:
   *  the API is down, DNS failed, CORS blocked it. Worth distinguishing,
   *  because the fix is "start the backend", not "fix your input". */
  offline: boolean;

  constructor(status: number, detail: string, offline = false) {
    super(detail);
    this.status = status;
    this.offline = offline;
  }
}

async function toError(res: Response): Promise<ApiError> {
  const body = (await res.json().catch(() => null)) as ApiErrorBody | null;
  return new ApiError(res.status, body?.detail ?? res.statusText);
}

/** Fetch that reports an unreachable API as such instead of a bare TypeError. */
async function send(path: string, init?: RequestInit): Promise<Response> {
  try {
    return await fetch(`${BASE_URL}${path}`, init);
  } catch {
    throw new ApiError(
      0,
      `cannot reach the API at ${BASE_URL}. Start it with \`docker compose up -d\`.`,
      true,
    );
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await send(path, init);
  if (!res.ok) throw await toError(res);
  return res.json() as Promise<T>;
}

export async function getHealth(): Promise<{ status: string }> {
  return request("/health");
}

export interface ScanOptions {
  /** Path inside the repo holding package.json, for monorepos. */
  subdir?: string;
  maxLen?: number;
  offline?: boolean;
  signal?: AbortSignal;
}

export async function scanRepo(repoUrl: string, opts: ScanOptions = {}): Promise<ScanReport> {
  return request("/scan", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      repo_url: repoUrl,
      subdir: opts.subdir?.trim() || null,
      max_len: opts.maxLen ?? 12,
      offline: opts.offline ?? false,
    }),
    signal: opts.signal,
  });
}

/**
 * Pull the suggested subdirectories out of the API's "wrong root" message.
 *
 * The server already worked out where the npm projects are; re-deriving that
 * in the client would mean a second clone. Parsing its sentence is the cheap
 * way to turn the error into one-click buttons.
 */
export function suggestedSubdirs(detail: string): string[] {
  const m = /found one in:\s*([^.]+?)(?:\s*\(\+\d+ more\))?\.\s*Re-run/i.exec(detail);
  if (!m) return [];
  return m[1]
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);
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
