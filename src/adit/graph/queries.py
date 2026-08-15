"""The entire query layer: reachability, blast radius, temporal validity.

Three shapes. Everything else in Adit is parameters over these.

The engine's read constraints shape all three:

  * variable-length MATCH requires a *fixed integer source id*, so names are
    resolved client-side before traversal;
  * relationships cannot be bound or filtered inside a variable-length match,
    so temporal predicates land on reified fact nodes instead;
  * `RETURN` projects only `<binding>.<property>` or `count(*)`, so paths come
    back exclusively via `algo.MSpaths`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from . import cypher
from .driver import Hydra
from .ids import node_id
from .schema import INVERSE_OF, Edge, FactKind, Label


@dataclass(slots=True)
class ReachPath:
    """One concrete path from an entrypoint to a target."""

    nodes: list[dict[str, Any]]

    @property
    def depth(self) -> int:
        return len(self.nodes) - 1

    @property
    def source_key(self) -> str:
        return str(self.nodes[0].get("key", ""))

    @property
    def target_key(self) -> str:
        return str(self.nodes[-1].get("key", ""))


@dataclass(slots=True)
class Reachability:
    """The answer to "does my code reach this?"

    `paths` empty means **no path exists** -- a fact, not a guess. Adit reports
    that as NOT_REACHABLE rather than inventing a chain, and records how much
    of the graph it explored so the negative answer is auditable.
    """

    reachable: bool
    paths: list[ReachPath]
    sources_considered: int
    targets_considered: int
    max_len: int

    @property
    def shortest(self) -> ReachPath | None:
        return min(self.paths, key=lambda p: p.depth) if self.paths else None

    def explain_absence(self) -> str:
        return (
            f"no path within {self.max_len} hops from any of "
            f"{self.sources_considered} entrypoint(s) to "
            f"{self.targets_considered} target(s)"
        )


class Queries:
    """Read-side operations against HydraDB."""

    def __init__(self, hydra: Hydra) -> None:
        self.hydra = hydra

    # -- Q1: reachability --------------------------------------------------
    def reachability(
        self,
        source_keys: list[str],
        target_keys: list[str],
        *,
        source_label: Label = Label.SYMBOL,
        rel: Edge = Edge.CALLS,
        max_len: int = 12,
        path_count: int = 3,
        result_limit: int = 500,
    ) -> Reachability:
        """Does a call path exist from any entrypoint to any target?

        One `algo.MSpaths` call resolves every (source, target) pair
        server-side. The naive alternative is `len(sources) * len(targets)`
        round trips -- for 200 services against 47 advisories that is 9,400.
        """
        if not source_keys or not target_keys:
            return Reachability(False, [], len(source_keys), len(target_keys), max_len)

        query = cypher.mspaths(
            source_label=source_label.value,
            source_keys=source_keys,
            target_keys=target_keys,
            rel_types=[rel.value],
            direction="outgoing",
            max_len=max_len,
            path_count=path_count,
            result_limit=result_limit,
        )
        paths = [ReachPath([dict(n) for n in p.nodes]) for p in self.hydra.run_paths(query)]
        return Reachability(
            reachable=bool(paths),
            paths=paths,
            sources_considered=len(source_keys),
            targets_considered=len(target_keys),
            max_len=max_len,
        )

    def reachability_fanout(
        self,
        source_keys: list[str],
        target_keys: list[str],
        *,
        rel: Edge = Edge.CALLS,
        max_len: int = 12,
    ) -> tuple[int, int]:
        """Deliberately naive client-side fan-out, for benchmarking only.

        Exists so the README can publish MSpaths against the alternative rather
        than asserting a speedup. Returns (paths_found, round_trips).
        """
        found = trips = 0
        for src in source_keys:
            sid = node_id(src)
            for tgt in target_keys:
                tid = node_id(tgt)
                trips += 1
                rows = self.hydra.run(
                    f"MATCH (a {{id: {sid}}})-[:{rel.value}*1..{max_len}]->"
                    f"(b {{id: {tid}}}) RETURN b.key AS key"
                )
                found += len(rows)
        return found, trips

    # -- Q2: blast radius --------------------------------------------------
    def blast_radius(
        self,
        target_key: str,
        *,
        rel: Edge = Edge.DEPENDS_ON,
        max_len: int = 10,
    ) -> list[str]:
        """Everything that transitively reaches `target_key`.

        This is the install-time-compromise query, where reachability is
        meaningless -- a preinstall hook runs whether or not you call the
        library -- so the whole answer is the transitive dependent set.

        Expressed as a *forward* traversal over the materialised inverse edge.
        The engine rejects both reverse spellings of a variable-length match
        ("variable-length MATCH requires a fixed source id"), so the inverse
        written at ingest is what makes reverse closure expressible at all.
        """
        twin = INVERSE_OF.get(rel)
        if twin is None:
            raise ValueError(
                f"{rel.value} has no materialised inverse; reverse closure is "
                f"not expressible for it (see schema.INVERSE_OF)"
            )
        rows = self.hydra.run(
            f"MATCH (bad {{id: {node_id(target_key)}}})-[:{twin.value}*1..{max_len}]->(d) "
            f"RETURN DISTINCT d.key AS key"
        )
        return [r["key"] for r in rows if r.get("key")]

    def callers_of(self, symbol_key: str, *, max_len: int = 8) -> list[str]:
        """Backward slice: what transitively calls this symbol?

        Falls out of the same materialised inverse. Answers "what breaks if I
        change this signature" -- a question embedding search cannot touch.
        """
        return self.blast_radius(symbol_key, rel=Edge.CALLS, max_len=max_len)

    # -- Q3: temporal validity --------------------------------------------
    def facts_in_window(
        self,
        subject_key: str,
        kind: FactKind,
        window_start: int,
        window_end: int,
    ) -> list[dict[str, Any]]:
        """Facts about `subject_key` whose validity overlaps the window.

        The predicate sits on the reified fact node, where range comparisons
        are fully supported -- relationships cannot be filtered inside a
        variable-length match, which is precisely why facts are nodes.

        This answers "which lockfiles resolved the bad version while it was
        live", the question that separates a real incident tool from a scanner.
        """
        return self.hydra.run(
            f"MATCH (s {{id: {node_id(subject_key)}}})<-[:{Edge.SUBJECT.value}]-"
            f"(f:{Label.FACT.value})-[:{Edge.OBJECT.value}]->(o) "
            f"WHERE f.kind = $kind AND f.valid_from < $end AND f.valid_to > $start "
            f"RETURN o.key AS object, f.valid_from AS valid_from, "
            f"f.valid_to AS valid_to, f.source AS source, f.confidence AS confidence "
            f"ORDER BY f.valid_from",
            kind=kind.value,
            start=window_start,
            end=window_end,
        )

    def exposed_services(
        self,
        release_key: str,
        window_start: int = 0,
        window_end: int = 2**62,
    ) -> list[dict[str, Any]]:
        """Which services resolved this exact release, and when.

        This is the incident-response question for an install-time compromise:
        not "what depends on lodash" (everything does) but "which of *my*
        services actually pulled down the bad bits, and was that during the
        window it was live".

        Both hops are single-hop, non-variable-length, so the transitive-reverse
        restriction that forced materialised inverse edges for blast radius does
        not apply -- but direction still matters in a way worth recording.
        SUBJECT and OBJECT both point forward, Fact -> node, so reaching a Fact
        from its *object* is a reverse hop and reaching the *subject* from that
        Fact is a forward hop. Chaining two REVERSE hops instead -- the natural
        way to write "walk backward twice" -- executes without error but
        silently returns zero rows; confirmed with scripts/chain_direction.py.
        Nothing in the engine's error text would have caught that, which is why
        the paired positive/negative test in test_deps_e2e.py exists.
        """
        return self.hydra.run(
            f"MATCH (rel {{id: {node_id(release_key)}}})<-[:{Edge.OBJECT.value}]-"
            f"(f:{Label.FACT.value})-[:{Edge.SUBJECT.value}]->(s) "
            f"WHERE f.kind = $kind AND f.valid_from < $end AND f.valid_to > $start "
            f"RETURN s.key AS service, f.valid_from AS valid_from, "
            f"f.observed_at AS observed_at, f.source AS source "
            f"ORDER BY f.valid_from",
            kind=FactKind.RESOLUTION.value,
            start=window_start,
            end=window_end,
        )

    # -- helpers -----------------------------------------------------------
    def key_exists(self, key: str) -> bool:
        """Does a node with this canonical key exist?

        `MATCH (n {id: X}) RETURN n.key` is NOT safe for this: for an id that
        was never written, the engine returns one row with every property
        null, rather than zero rows -- a bare id-only pattern with no attached
        relationship behaves as if the id space were dense and pre-allocated.
        Every traversal query is immune (`-[:REL]->` from a nonexistent anchor
        correctly yields zero rows, confirmed across every query in this file),
        so this is not a general correctness problem -- but it means naive
        existence checks silently always return True. Confirmed with
        `secrets.randbits(62)` against five fresh, guaranteed-unused ids, all
        of which "matched". See ARCHITECTURE.md.

        `n.key = n.key` forces the comparison to evaluate, and Cypher's
        three-valued logic makes NULL = NULL evaluate to false rather than
        true, which is what filters the phantom row out.
        """
        rows = self.hydra.run(
            f"MATCH (n {{id: {node_id(key)}}}) WHERE n.key = n.key RETURN n.key AS key"
        )
        return bool(rows)

    def neighbours(self, key: str, rel: Edge, *, limit: int = 100) -> list[str]:
        rows = self.hydra.run(
            f"MATCH (a {{id: {node_id(key)}}})-[:{rel.value}]->(b) "
            f"RETURN b.key AS key LIMIT {int(limit)}"
        )
        return [r["key"] for r in rows if r.get("key")]
