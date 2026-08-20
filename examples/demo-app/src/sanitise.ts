// Strips internal-only fields before an order crosses the service boundary.
//
// This is the reachable path in this example: `unset` is one of the functions
// OSV names for the prototype-pollution advisories affecting lodash@4.17.20
// (GHSA-f23m-r3pf-42rh and GHSA-xxjr-mmjv-4gpg), so a call graph that reaches
// here reaches a genuinely vulnerable symbol -- not a symbol chosen to make the
// demo work.
import { unset } from "lodash";

export function scrubOrder(order: unknown): unknown {
  const o = order as Record<string, unknown>;
  unset(o, ["internal", "auditTrail"]);
  unset(o, ["internal", "pricingNotes"]);
  return o;
}
