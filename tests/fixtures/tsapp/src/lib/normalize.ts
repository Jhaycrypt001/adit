// The only path in this repo that reaches lodash.
import { merge } from "lodash";

export function normalizePayload(input: unknown): unknown {
  return merge({}, input);
}

export function unusedHelper(): number {
  return 42;
}
