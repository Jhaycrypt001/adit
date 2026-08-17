"""Track 1 adapter: authority-ranked conflict resolution, third proof of the
same kernel. See ingest/enterprise.py's module docstring for exactly what is
real HERB data (entities, the product, the document id) versus constructed
(the specific conflicting values), and why -- three real search attempts for
an auto-minable contradiction in the actual HERB corpus came up empty, and
that negative result is reported rather than papered over.

The one assertion that matters: `test_authority_beats_recency_not_vice_versa`.
Timestamps are rigged so a recency-only sort gives the WRONG answer -- if
`best_claim` ever regresses to plain `ORDER BY valid_from DESC`, this is the
test that catches it, not a coincidence that happens to still pass.
"""

from __future__ import annotations

import os

import pytest

from adit.graph import Hydra, Queries
from adit.ingest.enterprise import SAMPLE_CLAIMS, SOURCE_TIER, EnterpriseClaim, emit_claims

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def hydra():
    uri = os.environ.get("ADIT_BOLT_URI", "bolt://127.0.0.1:7687")
    h = Hydra(uri)
    try:
        h.verify()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"no HydraDB at {uri}: {exc}")
    yield h
    h.close()


@pytest.fixture(scope="module")
def ingested(hydra):
    n = emit_claims(SAMPLE_CLAIMS, hydra)
    return n


def test_all_sample_claims_are_written(ingested):
    assert ingested == len(SAMPLE_CLAIMS) == 3


def test_source_tier_hierarchy_is_document_over_transcript_over_slack():
    assert SOURCE_TIER["document"] > SOURCE_TIER["meeting_transcript"] > SOURCE_TIER["slack"]


def test_best_claim_picks_the_highest_authority_source(ingested, hydra):
    """The document (tier 3) wins over the meeting transcript (tier 2), even
    though the transcript is the more recent of the two."""
    q = Queries(hydra)
    result = q.best_claim("entity:eid_9b023657", "cforceaix launch date")
    assert result is not None
    assert result["object"] == "2026-04-15"
    assert result["source_kind"] == "document"
    assert result["source"] == "final_cforceaix_product_requirements_document"


def test_authority_beats_recency_not_vice_versa(ingested, hydra):
    """The thesis, proven adversarially. The meeting transcript's valid_from
    (1_735_400_000) is LATER than the document's (1_735_100_000) -- so
    `ORDER BY valid_from DESC LIMIT 1` alone would pick the transcript's
    "2026-04-01" and be wrong. best_claim must not do that."""
    q = Queries(hydra)
    all_claims = q.all_claims("entity:eid_9b023657", "cforceaix launch date")
    by_kind = {c["source_kind"]: c for c in all_claims}
    assert by_kind["meeting_transcript"]["valid_from"] > by_kind["document"]["valid_from"], (
        "fixture invariant broken: the adversarial timing this test depends on is gone"
    )

    result = q.best_claim("entity:eid_9b023657", "cforceaix launch date")
    assert result["source_kind"] == "document", (
        "best_claim picked the more RECENT source over the more AUTHORITATIVE "
        "one -- this is exactly the regression the test exists to catch"
    )


def test_all_claims_shows_the_full_disagreement_ranked(ingested, hydra):
    """Adit shows its work: the two claims it overrode are still visible, in
    the same rank order that produced the answer."""
    q = Queries(hydra)
    all_claims = q.all_claims("entity:eid_9b023657", "cforceaix launch date")
    assert len(all_claims) == 3
    assert [c["source_kind"] for c in all_claims] == [
        "document", "meeting_transcript", "slack",
    ]
    assert [c["object"] for c in all_claims] == ["2026-04-15", "2026-04-01", "2026-03-01"]


def test_best_claim_abstains_on_a_subject_never_asserted(ingested, hydra):
    q = Queries(hydra)
    assert q.best_claim("entity:eid_9b023657", "favourite ide") is None


def test_best_claim_abstains_on_an_unknown_entity(ingested, hydra):
    q = Queries(hydra)
    assert q.best_claim("entity:eid_totally_made_up", "cforceaix launch date") is None


def test_unknown_source_kind_is_rejected_not_silently_ranked(hydra):
    """A claim with a source kind outside SOURCE_TIER must fail loudly at
    write time, not silently sort as if it had some default authority."""
    bad = EnterpriseClaim(
        entity="eid_9b023657", subject="x", value="y",
        source_kind="carrier-pigeon", source_id="s", observed_at=1, text="t",
    )
    with pytest.raises(ValueError, match="unknown source kind"):
        emit_claims([bad], hydra)


def test_provenance_text_is_the_real_source_sentence(ingested, hydra):
    q = Queries(hydra)
    result = q.best_claim("entity:eid_9b023657", "cforceaix launch date")
    assert "April 15" in result["text"]
