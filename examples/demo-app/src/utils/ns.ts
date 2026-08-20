// Namespace import: helpers.pad() must resolve through the namespace binding.
import * as helpers from "./helpers";

export function useNamespace(): string {
  return helpers.pad("x");
}
