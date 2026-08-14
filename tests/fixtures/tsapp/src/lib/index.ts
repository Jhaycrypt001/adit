// Barrel file. `export *` is the construct that defeats naive extractors:
// nothing here names normalizePayload, yet importers resolve it through here.
export * from "./normalize";
export { padLeft as pad } from "./format";
