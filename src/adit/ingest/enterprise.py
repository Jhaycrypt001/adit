"""Track 1 adapter: enterprise conflict resolution, on the same kernel again.

Third domain, same proof as Track 3's ingest/memory.py: the identical bitemporal
`Claim` shape and an `ORDER BY ... LIMIT 1` ranking answer a structurally
different question with no new query primitive, only a different sort key.

    Track 3 (memory):     rank claims by RECENCY alone -- "the latest update wins"
    Track 1 (enterprise):  rank claims by AUTHORITY, then recency -- "the most
                            credible source wins, ties broken by time"

That second axis is real and load-bearing, not decoration: an enterprise
knowledge base has documents, meeting transcripts and chat messages of
genuinely different trustworthiness, and a system that only sorts by time will
happily let a stale Slack aside outrank a finalized, later-superseded-by-
nothing formal document. `Claim.source_tier` and the two-column `ORDER BY`
this adapter introduces are what make that distinction real rather than
assumed -- confirmed against a live engine before relying on it (multi-column
ORDER BY was never exercised by Track 3, which only ever needed one column).

**Entities are real, the specific conflict is not auto-mined -- said plainly.**
Employee records, product name and identifiers below come from HERB
(github.com/SalesforceAIResearch/HERB, data/metadata/employee.json and
data/products/CollaborationForce.json), not invented. Finding a genuine,
unambiguous same-fact numeric contradiction in that corpus was attempted with
the same declared-pattern approach used for Track 3 and it came up empty on
three real searches:

  1. a generic quantity-pattern scan across slack/documents/meeting_transcripts
     surfaced "revenue" and "cost" mentions with different numbers, but every
     one was either near-duplicate documents repeating the identical figure,
     or two genuinely different quantities (a competitor's line-item price vs.
     this product's own total) coincidentally sharing a keyword;
  2. cross-checking each employee's canonical role (employee.json) against
     their per-product team listing found no per-product role field to compare
     against at all -- `team` is a flat list of employee ids, no role attached;
  3. no HERB question is tagged or worded as a conflict/contradiction case --
     the track brief's "Conflicting Info" category belongs to the *other*
     Track 1 dataset (EnterpriseRAG-Bench), not HERB.

So the two conflicting claims below are constructed, using real entity ids and
a real product, to exercise the ranking mechanism -- exactly the same honesty
line Stage D draws for its tier-3 fallback: never presented as more than it is.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..graph import Edge, Hydra, Label, Node, Writer
from ..graph.schema import FOREVER, validate_props

#: Higher outranks lower. A finalized document beats a transcript beats an
#: informal chat aside -- the ordinary provenance hierarchy of a real
#: enterprise knowledge base, encoded as an integer because ORDER BY only
#: sorts on properties, not on an application-side enum.
SOURCE_TIER = {
    "document": 3,
    "meeting_transcript": 2,
    "slack": 1,
}


@dataclass(slots=True)
class EnterpriseClaim:
    entity: str          # real HERB employee id or product id
    subject: str          # normalised attribute name
    value: str
    source_kind: str      # one of SOURCE_TIER's keys
    source_id: str        # a real HERB artifact/document id, for provenance
    observed_at: int       # epoch seconds
    text: str              # the sentence it came from


#: Real HERB entities (data/metadata/employee.json, data/products/
#: CollaborationForce.json) carrying a constructed, clearly-labelled conflict
#: -- see the module docstring for why this pair is hand-built rather than
#: mined. Both claims are about the SAME real employee and the SAME subject;
#: only the source and value differ, which is exactly what the ranking query
#: needs to resolve.
#: Timestamps are deliberately NOT monotonic with source authority. The
#: meeting transcript is the MOST RECENT of the three, one tier below the
#: document -- so a ranking that only sorted by recency would pick it, and
#: get the wrong answer. Only a rank that checks source_tier first, recency
#: second, resolves to the document correctly. That is the actual claim this
#: adapter makes: authority beats recency, not merely "and also has recency".
SAMPLE_CLAIMS: list[EnterpriseClaim] = [
    EnterpriseClaim(
        entity="eid_9b023657",  # Hannah Taylor, VP of Engineering (real, employee.json)
        subject="cforceaix launch date",
        value="2026-03-01",
        source_kind="slack",
        source_id="slack:collaborationforce:hannah-taylor:launch-eta",
        observed_at=1_735_000_000,   # earliest of the three
        text="yeah realistically I think we're looking at launching CForceAIX "
             "around March 1st if nothing slips",
    ),
    EnterpriseClaim(
        entity="eid_9b023657",
        subject="cforceaix launch date",
        value="2026-04-15",
        source_kind="document",
        source_id="final_cforceaix_product_requirements_document",  # real HERB doc id
        observed_at=1_735_100_000,   # earlier than the transcript below
        text="Launch Timeline: CForceAIX is scheduled for general availability "
             "on April 15, 2026, pending final QA sign-off.",
    ),
    EnterpriseClaim(
        entity="eid_9b023657",
        subject="cforceaix launch date",
        value="2026-04-01",
        source_kind="meeting_transcript",
        source_id="meeting:collaborationforce:planning-sync-03",
        observed_at=1_735_400_000,   # LATEST of the three, but one tier below
        text="Per the planning sync: target GA is April 1st, pending the "
             "requirements doc being finalised.",
    ),
]


def emit_claims(claims: list[EnterpriseClaim], hydra: Hydra) -> int:
    """Write enterprise claims, ranked by real source-authority tiers."""
    w = Writer(hydra)

    entities = {c.entity for c in claims}
    w.upsert_nodes(
        [Node(key=f"entity:{eid}", label=Label.ENTITY, props={"kind": "employee"})
         for eid in entities]
    )

    nodes: list[Node] = []
    edges: list[tuple[str, str]] = []
    for c in claims:
        tier = SOURCE_TIER.get(c.source_kind)
        if tier is None:
            raise ValueError(f"unknown source kind: {c.source_kind!r}")
        claim_key = f"claim:{c.entity}:{c.subject}:{c.value}:{c.observed_at}"
        props = {
            "subject": c.subject,
            "predicate": "has_value",
            "object": c.value,
            "text": c.text,
            "source": c.source_id,
            "source_kind": c.source_kind,
            "source_tier": tier,
            "valid_from": c.observed_at,
            "valid_to": FOREVER,
            "observed_at": c.observed_at,
            "confidence": 1.0,
        }
        validate_props(props)
        nodes.append(Node(key=claim_key, label=Label.CLAIM, props=props))
        edges.append((f"entity:{c.entity}", claim_key))

    w.upsert_nodes(nodes)
    w.create_edges(Edge.ASSERTS, edges, inverse=False)
    return len(nodes)
