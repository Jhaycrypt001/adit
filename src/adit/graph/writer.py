"""The three write paths, and the rules that force them apart.

Measured on HydraDB (see scripts/throughput.py):

    UNWIND ... MERGE (n {id}) SET n:L, n.p = r.p    ~14,500 nodes/sec, full props
    UNWIND ... CREATE (a {id})-[:T]->(b {id})       ~10,000 edges/sec, NO props
    CREATE (a {id})-[:T {p: 1}]->(b {id})               ~5-10 edges/sec, full props

Everything chunks at 1024 rows. There are no explicit transactions, so every
method here is idempotent and a partial run is safe to repeat -- it leaves a
valid, incomplete graph rather than a corrupt one.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

from .driver import Hydra
from .ids import IdRegistry, fact_key, node_id
from .schema import INVERSE_OF, Edge, Fact, Label, Node, validate_props

log = logging.getLogger(__name__)

# `MERGE (n {id: r.id})` matches on id alone; the label must be applied with SET
# ("UNWIND vertex upsert MERGE pattern matches only id; apply labels with SET"),
# and exactly one label is permitted per statement.
_UPSERT = "UNWIND $rows AS r MERGE (n {{id: r.id}}) SET n:{label}, {assigns}"

# Batched edges take one fixed relationship type and no properties.
_EDGE = "UNWIND $rows AS r CREATE (a {{id: r.src}})-[:{rel}]->(b {{id: r.dst}})"


class Writer:
    """Stages and flushes graph writes."""

    def __init__(self, hydra: Hydra) -> None:
        self.hydra = hydra
        self.ids = IdRegistry()
        self.stats: dict[str, int] = {}

    # -- nodes -------------------------------------------------------------
    def upsert_nodes(self, nodes: Sequence[Node]) -> int:
        """Upsert nodes with full properties. The fast path.

        Grouped by (label, property-key-set) because one statement can apply
        only one label, and every row in a batch must assign the same columns.
        """
        if not nodes:
            return 0

        groups: dict[tuple[Label, tuple[str, ...]], list[Node]] = {}
        for n in nodes:
            validate_props(n.props)
            groups.setdefault((n.label, tuple(sorted(n.props))), []).append(n)

        total = 0
        for (label, prop_names), group in groups.items():
            assigns = ", ".join(f"n.{p} = r.{p}" for p in ("key", *prop_names))
            cypher = _UPSERT.format(label=label.value, assigns=assigns)
            rows = [
                {"id": self.ids.register(n.key), "key": n.key, **n.props} for n in group
            ]
            total += self.hydra.run_batched(cypher, rows)
            log.debug("upserted %d %s nodes", len(rows), label.value)

        self.stats["nodes"] = self.stats.get("nodes", 0) + total
        return total

    # -- topology edges ----------------------------------------------------
    def create_edges(
        self, rel: Edge, pairs: Sequence[tuple[str, str]], *, inverse: bool = True
    ) -> int:
        """Create bare topology edges between existing nodes, by key.

        Property-free by necessity -- the engine rejects properties on batched
        edges. Anything needing a lifetime is a reified fact instead.

        Note the engine upserts endpoint nodes by id rather than requiring them
        to exist, and does not clobber properties already set on them, so edge
        writes are order-independent with respect to node writes.

        For edge types in INVERSE_OF the inverse is materialised too. The engine
        cannot express transitive *reverse* closure -- variable-length MATCH must
        run forward from a fixed source id -- so the inverse edge is the only way
        to answer "what reaches this?". Pass ``inverse=False`` to suppress it.
        """
        if not pairs:
            return 0

        rows = [{"src": node_id(s), "dst": node_id(d)} for s, d in pairs]
        sent = self.hydra.run_batched(_EDGE.format(rel=rel.value), rows)
        self.stats[rel.value] = self.stats.get(rel.value, 0) + sent

        twin = INVERSE_OF.get(rel) if inverse else None
        if twin is not None:
            flipped = [{"src": r["dst"], "dst": r["src"]} for r in rows]
            n = self.hydra.run_batched(_EDGE.format(rel=twin.value), flipped)
            self.stats[twin.value] = self.stats.get(twin.value, 0) + n

        return sent

    # -- reified temporal facts -------------------------------------------
    def upsert_facts(self, facts: Sequence[Fact]) -> int:
        """Write temporal facts as nodes, then wire them to subject and object.

        Three batched statements per group instead of one slow propertied edge
        per fact: the fact nodes upsert at node speed, and the two SUBJECT /
        OBJECT edges ride the batched edge path.
        """
        if not facts:
            return 0

        nodes: list[Node] = []
        subject_pairs: list[tuple[str, str]] = []
        object_pairs: list[tuple[str, str]] = []

        for f in facts:
            key = fact_key(
                f.kind.value, f.subject_key, f.object_key, f.provenance.valid_from
            )
            validate_props(f.props)
            nodes.append(
                Node(
                    key=key,
                    label=Label.FACT,
                    props={
                        "kind": f.kind.value,
                        **f.provenance.as_properties(),
                        **f.props,
                    },
                )
            )
            subject_pairs.append((key, f.subject_key))
            object_pairs.append((key, f.object_key))

        self.upsert_nodes(nodes)
        self.create_edges(Edge.SUBJECT, subject_pairs)
        self.create_edges(Edge.OBJECT, object_pairs)

        self.stats["facts"] = self.stats.get("facts", 0) + len(facts)
        return len(facts)

    # -- diagnostics -------------------------------------------------------
    def summary(self) -> str:
        parts = [f"{v:,} {k}" for k, v in sorted(self.stats.items())]
        return ", ".join(parts) if parts else "nothing written"
