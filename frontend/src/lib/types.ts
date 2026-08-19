// Mirrors src/adit/render.py::to_json and src/adit/api.py's response shapes
// exactly -- see ARCHITECTURE.md for the query model behind these fields.

export type Status = "reachable" | "not_reachable" | "unresolved";
export type AdvisoryClass = "install_time" | "runtime" | "unknown";

export interface PathNode {
  name: string | null;
  file: string | null;
  line: number | null;
}

export interface SymbolResolution {
  names: string[];
  tier: number;
  confidence: number;
  method: string;
}

export interface Finding {
  advisory_id: string;
  summary: string;
  severity: string;
  class: AdvisoryClass;
  package: string;
  actionable: boolean;
  status: Status;
  reachable: boolean;
  reason: string;
  symbol: SymbolResolution | null;
  paths: PathNode[][];
  blast_radius: string[];
}

export interface ScanReport {
  package: string;
  root: string;
  headline: string;
  findings: Finding[];
  timings: Record<string, number>;
  elapsed: number;
  scan_id: string;
}

export interface ExposedService {
  service: string;
  source: string;
  [key: string]: unknown;
}

export interface BlastResult {
  package: string;
  dependent_packages: string[];
  exposed_services: ExposedService[];
}

export interface WhyResult {
  reachable: boolean;
  explanation?: string;
  depth?: number;
  path?: PathNode[];
}

export interface ApiErrorBody {
  detail: string;
}
