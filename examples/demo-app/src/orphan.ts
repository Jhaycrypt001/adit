// Nothing imports this, and its call target does not exist in the project.
// It must stay unreachable and its call must be counted as unresolved rather
// than guessed at.
export function orphan(): void {
  unknownGlobalThing();
}
