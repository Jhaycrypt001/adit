"""Labels, edge classes, and the reified-fact model.

The engine forces every edge to be one of two things:

  * batched, ~10,000/sec, and carrying **no properties**, or
  * individually written at ~5-10/sec, carrying full properties.

Rather than compromise, Adit splits by the nature of the fact. Topology is
timeless and high-volume, so it uses bare batched edges. Anything with a
lifetime becomes a **reified fact node**, which upserts on the fast path
(~14,500/sec) and carries the full temporal/provenance quad.

This is a better model than properties-on-edges, not a workaround: a reified
fact can be superseded, can carry provenance and confidence, and can hold
several independent observations of the same relationship.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

#: Sentinel for "still true". Comfortably beyond any real timestamp while
#: staying well inside signed 64-bit so no driver narrows it.
FOREVER = 4_102_444_800_000  # 2100-01-01T00:00:00Z in epoch ms


class Label(StrEnum):
    """Node labels."""

    SYMBOL = "Symbol"        # a function / method / class
    MODULE = "Module"        # a file or module
    PACKAGE = "Package"      # a package, version-independent
    RELEASE = "Release"      # a specific published version
    SERVICE = "Service"      # a deployable unit owning a lockfile
    ADVISORY = "Advisory"    # a CVE / GHSA
    IDENTITY = "Identity"    # a maintainer / person (shared with track 1)
    ENTITY = "Entity"        # an enterprise entity (track 1)
    EPISODE = "Episode"      # a session or document (tracks 1 and 3)
    CLAIM = "Claim"          # a reified assertion (tracks 1 and 3)
    FACT = "Fact"            # a reified temporal fact (all tracks)


class Edge(StrEnum):
    """Topology edge types. Batched, high-volume, and property-free."""

    CALLS = "CALLS"              # Symbol  -> Symbol
    IMPORTS = "IMPORTS"          # Module  -> Module | Package
    DEFINES = "DEFINES"          # Module  -> Symbol
    EXPORTS = "EXPORTS"          # Release -> Symbol   (the package boundary)
    DEPENDS_ON = "DEPENDS_ON"    # Release -> Release
    MAINTAINS = "MAINTAINS"      # Identity -> Package
    ABOUT = "ABOUT"              # Claim   -> Entity
    SAME_AS = "SAME_AS"          # entity resolution
    #: Entity/Episode -> Claim. Claims carry their own bitemporal quad directly
    #: (see ingest/memory.py) rather than through a separate Fact indirection,
    #: so "the current value" is one fixed-source hop with a range filter --
    #: the same query shape as Q3, not a new primitive.
    ASSERTS = "ASSERTS"
    #: Advisory -> the specific Symbol it implicates. The target of every
    #: reachability query; see ingest/symbols.py for how it is derived.
    VULNERABLE_SYMBOL = "VULNERABLE_SYMBOL"
    #: The two halves of a reified fact. Traversals through a fact cost two
    #: hops, so `max_len` budgets must account for it.
    SUBJECT = "SUBJECT"          # Fact -> subject node
    OBJECT = "OBJECT"            # Fact -> object node
    #: Materialised inverses -- see INVERSE_OF below.
    CALLED_BY = "CALLED_BY"          # Symbol  <- Symbol
    DEPENDED_ON_BY = "DEPENDED_ON_BY"  # Release <- Release


#: Edge types whose inverse is materialised at ingest.
#:
#: The engine requires a variable-length MATCH to run *forward from a fixed
#: integer source id*. Both reverse spellings are rejected outright:
#:
#:     MATCH (bad {id: X})<-[:DEPENDS_ON*1..5]-(d)   -> rejected
#:     MATCH (d)-[:DEPENDS_ON*1..5]->(bad {id: X})   -> rejected
#:
#: Single-hop reverse works, but transitive reverse closure -- the entire blast
#: radius query -- has no direct expression. So Adit writes the inverse edge
#: explicitly and traverses it forward. Batched edges cost ~10,000/sec, which
#: makes this the cheap answer rather than a compromise.
#:
#: It also buys backward slicing for free: "what calls this function", i.e.
#: what breaks if I change it.
INVERSE_OF: dict[Edge, Edge] = {
    Edge.CALLS: Edge.CALLED_BY,
    Edge.DEPENDS_ON: Edge.DEPENDED_ON_BY,
}


class FactKind(StrEnum):
    """Reified temporal facts -- edges that needed a lifetime."""

    RESOLUTION = "resolution"    # a Service's lockfile resolved a Release, in a window
    EXPOSURE = "exposure"        # an Advisory affected a Release
    OBSERVATION = "observation"  # an Episode asserted a Claim
    SUPERSESSION = "supersession"  # a Claim replaced an earlier Claim


class AdvisoryClass(StrEnum):
    """How an advisory must be analysed.

    The distinction most tools miss, and it inverts the analysis:

    * INSTALL_TIME -- a preinstall/postinstall hook (the keyv compromise, the
      TanStack worm). The payload runs at `npm install` whether or not the
      library is ever called, so **reachability is meaningless** and blast
      radius plus the temporal window is everything.
    * RUNTIME -- an ordinary library-function CVE. Everyone depends on lodash,
      so **blast radius is noise** and reachability is everything.
    """

    INSTALL_TIME = "install_time"
    RUNTIME = "runtime"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class Provenance:
    """The quad every reified fact carries.

    Bitemporal: `valid_from`/`valid_to` is when the fact was true *in the
    world*; `observed_at` is when Adit learned it. Keeping both is what lets us
    answer "what did we believe last Tuesday" separately from "what was
    actually true last Tuesday".
    """

    valid_from: int
    observed_at: int
    source: str
    valid_to: int = FOREVER
    confidence: float = 1.0

    def __post_init__(self) -> None:
        if self.valid_to < self.valid_from:
            raise ValueError(f"valid_to {self.valid_to} precedes valid_from {self.valid_from}")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"confidence out of range: {self.confidence}")

    def as_properties(self) -> dict[str, Any]:
        return {
            "valid_from": self.valid_from,
            "valid_to": self.valid_to,
            "observed_at": self.observed_at,
            "source": self.source,
            "confidence": self.confidence,
        }


@dataclass(slots=True)
class Node:
    """A node staged for upsert."""

    key: str
    label: Label
    props: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class Fact:
    """A reified temporal fact linking two existing nodes."""

    kind: FactKind
    subject_key: str
    object_key: str
    provenance: Provenance
    props: dict[str, Any] = field(default_factory=dict)


#: Property names reserved by the engine or by Adit's identity scheme.
RESERVED_PROPS = frozenset({"id", "key"})


def validate_props(props: dict[str, Any]) -> None:
    """Reject property maps the engine cannot store.

    Property values support integer, float, boolean and string only -- no
    lists, no maps, no null. Caught here so it surfaces at the call site rather
    than as an opaque syntax error from a batch of 1024 rows.
    """
    for name, value in props.items():
        if name in RESERVED_PROPS:
            raise ValueError(f"{name!r} is reserved and set by the writer")
        if not isinstance(value, (int, float, bool, str)):
            raise ValueError(
                f"property {name!r} has unsupported type {type(value).__name__}; "
                "engine accepts integer, float, boolean, string"
            )
