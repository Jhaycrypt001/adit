"""Track 3 adapter: chat sessions onto the same reachability kernel.

This exists to prove a claim made in ARCHITECTURE.md, not to compete with
Mem0 or Zep on a benchmark: the SAME bitemporal Fact schema built for Track 2's
"was this lockfile resolution live during the compromise window" answers
Track 3's "knowledge update" questions with the identical query shape,
`WHERE valid_from <= as_of ORDER BY valid_from DESC LIMIT 1`.

**Extraction here is real, declared, and narrow -- not fabricated.** Full
open-domain claim extraction from chat is an NLP problem real memory systems
(Mem0, Zep/Graphiti) solve with an LLM call per ingested episode, which this
project's zero-LLM-on-the-critical-path constraint puts out of scope. What
ships instead is a single, generic pattern family -- "a named quantity has a
value with a unit" (a personal-best time, a price, a weight, a score) -- run
against RAW session text with no access to the dataset's own answer-key
labels. It is honestly weak on prose that does not fit the pattern, and the
adapter reports its own hit rate rather than implying completeness, the same
way stage A reports its call-site bind rate.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from ..graph import Edge, Hydra, Label, Node, Writer
from ..graph.schema import FOREVER, validate_props

log = logging.getLogger(__name__)

#: Matches "personal best (time) of 25:50", "record of 12.3kg", "score of 87",
#: "price of $42.50" -- a named quantity followed by a value with an optional
#: unit. Deliberately narrow: it is the one pattern family common enough across
#: LongMemEval's templated fact-injection to be worth writing, not a general
#: information-extraction system.
_QUANTITY = re.compile(
    r"(?P<subject>(?:personal\s+best|record|high\s+score|score|rating|price|"
    r"weight|budget|salary|time)s?)"
    r"(?:\s+(?:of|is|was|to|for|at))?\s*"
    r"(?:of\s+)?\$?"
    r"(?P<value>\d{1,3}(?:,\d{3})*(?:\.\d+)?(?::\d{2}(?::\d{2})?)?)"
    # A closed unit vocabulary, not a generic short-word catch-all: an
    # earlier `[a-z]{1,4}` matched whatever English word happened to follow
    # the number -- "25:50 this time around" captured "this" as if it were a
    # unit, corrupting the value to "25:50this". Absent a real unit, leave it
    # blank rather than guess.
    r"\s*(?P<unit>kg|lbs?|miles?|km|mph|%)?",
    re.IGNORECASE,
)

_DATE_FORMATS = ("%Y/%m/%d (%a) %H:%M",)


def parse_date(text: str) -> int:
    """LongMemEval dates: '2023/05/25 (Thu) 20:21'. Returns epoch seconds."""
    import datetime

    for fmt in _DATE_FORMATS:
        try:
            return int(datetime.datetime.strptime(text, fmt).replace(
                tzinfo=datetime.UTC
            ).timestamp())
        except ValueError:
            continue
    raise ValueError(f"unrecognised date format: {text!r}")


@dataclass(slots=True)
class ExtractedClaim:
    subject: str          # normalised quantity name, e.g. "personal best"
    value: str             # raw matched value, e.g. "25:50"
    unit: str              # "" if none matched
    source_text: str       # the sentence it came from, for provenance
    valid_from: int        # session date, epoch seconds
    session_id: str

    @property
    def object(self) -> str:
        return f"{self.value}{self.unit}"


@dataclass(slots=True)
class Turn:
    role: str
    content: str
    has_answer: bool = False


@dataclass(slots=True)
class Session:
    session_id: str
    date_text: str
    turns: list[Turn]

    @property
    def valid_from(self) -> int:
        return parse_date(self.date_text)


@dataclass(slots=True)
class MemoryItem:
    """One LongMemEval haystack: a persona's session history plus one question."""

    question_id: str
    question_type: str
    question: str
    answer: str
    question_date: str
    sessions: list[Session]
    is_abstention: bool = False

    @property
    def owner(self) -> str:
        """Namespace shared by every session in this haystack.

        LongMemEval session ids look like `answer_<hash>_<n>`; the hash
        identifies the persona the sessions belong to, and is stable across
        all sessions in one item's haystack.
        """
        for s in self.sessions:
            m = re.match(r"[a-z]+_([0-9a-f]{6,})_", s.session_id)
            if m:
                return m.group(1)
        return self.question_id


def load_longmemeval(path: Path, *, limit: int | None = None) -> list[MemoryItem]:
    """Parse the LongMemEval oracle/cleaned JSON format."""
    raw = json.loads(path.read_text("utf-8"))
    items = []
    for entry in raw[:limit] if limit else raw:
        sessions = [
            Session(
                session_id=sid,
                date_text=date,
                turns=[
                    Turn(t["role"], t["content"], bool(t.get("has_answer", False)))
                    for t in turns
                ],
            )
            for sid, date, turns in zip(
                entry["haystack_session_ids"], entry["haystack_dates"],
                entry["haystack_sessions"], strict=True,
            )
        ]
        items.append(
            MemoryItem(
                question_id=entry["question_id"],
                question_type=entry["question_type"],
                question=entry["question"],
                answer=entry["answer"],
                question_date=entry["question_date"],
                sessions=sessions,
                is_abstention=entry["question_id"].endswith("_abs"),
            )
        )
    return items


def extract_claims(session: Session) -> list[ExtractedClaim]:
    """Run the quantity pattern over every user turn in a session.

    User turns only: an assistant's paraphrase of what the user said is not a
    new fact, and treating it as one would double-count every claim.
    """
    out = []
    valid_from = session.valid_from
    for turn in session.turns:
        if turn.role != "user":
            continue
        for match in _QUANTITY.finditer(turn.content):
            subject = re.sub(r"\s+", " ", match.group("subject").lower()).rstrip("s")
            out.append(
                ExtractedClaim(
                    subject=subject,
                    value=match.group("value"),
                    unit=(match.group("unit") or "").lower(),
                    source_text=turn.content[:200],
                    valid_from=valid_from,
                    session_id=session.session_id,
                )
            )
    return out


@dataclass
class MemoryIngestResult:
    owner: str
    sessions_written: int = 0
    claims_extracted: int = 0
    sessions_with_no_claim: int = 0
    claims_by_subject: dict[str, int] = field(default_factory=dict)

    def summary(self) -> str:
        rate = (
            (self.sessions_written - self.sessions_with_no_claim) / self.sessions_written
            if self.sessions_written else 0.0
        )
        return (
            f"{self.sessions_written} sessions, {self.claims_extracted} claims "
            f"extracted, {rate:.0%} of sessions yielded at least one claim"
        )


def emit_item(item: MemoryItem, hydra: Hydra) -> MemoryIngestResult:
    """Write one persona's session history as Episodes and Claims.

    Claims carry their own bitemporal quad (valid_from/valid_to/observed_at/
    source/confidence) directly as properties, wired to their owning Entity by
    one batched ASSERTS edge. That keeps "what is the current value" a single
    fixed-source hop with a range filter -- proven shapes, no new query
    primitive, and no untested multi-hop mixed-direction chain.
    """
    w = Writer(hydra)
    result = MemoryIngestResult(owner=item.owner)

    owner_key = f"entity:{item.owner}"
    w.upsert_nodes([Node(key=owner_key, label=Label.ENTITY, props={"kind": "memory_owner"})])

    episodes = [
        Node(
            key=f"episode:{item.owner}:{s.session_id}",
            label=Label.EPISODE,
            props={"session_id": s.session_id, "occurred_at": s.valid_from},
        )
        for s in item.sessions
    ]
    w.upsert_nodes(episodes)
    result.sessions_written = len(episodes)

    claim_nodes: list[Node] = []
    asserts_edges: list[tuple[str, str]] = []
    episode_edges: list[tuple[str, str]] = []

    for session in item.sessions:
        claims = extract_claims(session)
        if not claims:
            result.sessions_with_no_claim += 1
            continue
        for claim in claims:
            result.claims_extracted += 1
            result.claims_by_subject[claim.subject] = (
                result.claims_by_subject.get(claim.subject, 0) + 1
            )
            claim_key = f"claim:{item.owner}:{claim.subject}:{claim.object}:{claim.valid_from}"
            props = {
                "subject": claim.subject,
                "predicate": "has_value",
                "object": claim.object,
                "text": claim.source_text,
                "valid_from": claim.valid_from,
                "valid_to": FOREVER,
                "observed_at": claim.valid_from,
                "source": "longmemeval",
                "confidence": 1.0,
            }
            validate_props(props)
            claim_nodes.append(Node(key=claim_key, label=Label.CLAIM, props=props))
            asserts_edges.append((owner_key, claim_key))
            episode_edges.append((f"episode:{item.owner}:{claim.session_id}", claim_key))

    w.upsert_nodes(claim_nodes)
    w.create_edges(Edge.ASSERTS, asserts_edges, inverse=False)
    # Episode -> Claim uses the same edge type for provenance lookups ("which
    # session said this"); it is not on the current-value query path, so no
    # inverse is needed for it either.
    w.create_edges(Edge.ASSERTS, episode_edges, inverse=False)

    log.info("memory ingest %s: %s", item.owner, result.summary())
    return result
