"""Which variable-length direction forms does the engine accept?

`MATCH (bad {id: X})<-[:DEP*1..5]-(d)` is rejected with "variable-length MATCH
requires a fixed source id", which suggests the anchor must sit at the
*traversal source* rather than anywhere in the pattern. If so, reverse closure
-- the blast-radius query -- has no direct expression and needs materialised
inverse edges. Confirm before adding that machinery.
"""

from __future__ import annotations

from adit.graph import Hydra

FORMS = [
    ("reverse arrow, id on left", "MATCH (bad {id: 7000003})<-[:DEP*1..5]-(d) RETURN d.key AS key"),
    ("forward arrow, id on right", "MATCH (d)-[:DEP*1..5]->(bad {id: 7000003}) RETURN d.key AS key"),
    ("forward, id on left (control)", "MATCH (s {id: 7000001})-[:DEP*1..5]->(d) RETURN d.key AS key"),
    ("reverse, single hop (no *)", "MATCH (bad {id: 7000003})<-[:DEP]-(d) RETURN d.key AS key"),
    ("materialised inverse edge", "MATCH (s {id: 7000003})-[:DEP_BY*1..5]->(d) RETURN d.key AS key"),
]


def main() -> int:
    h = Hydra()
    h.verify()

    # r1 -> r2 -> r3, plus the materialised inverse chain r3 -> r2 -> r1.
    h.run("CREATE (a {id: 7000001, key: 'r1'})-[:DEP]->(b {id: 7000002, key: 'r2'})")
    h.run("CREATE (a {id: 7000002, key: 'r2'})-[:DEP]->(b {id: 7000003, key: 'r3'})")
    h.run("CREATE (a {id: 7000003, key: 'r3'})-[:DEP_BY]->(b {id: 7000002, key: 'r2'})")
    h.run("CREATE (a {id: 7000002, key: 'r2'})-[:DEP_BY]->(b {id: 7000001, key: 'r1'})")

    for note, cypher in FORMS:
        try:
            rows = h.run(cypher)
            print(f"  PASS  {note:32} -> {sorted(str(r['key']) for r in rows)}")
        except Exception as exc:  # noqa: BLE001
            msg = str(exc)
            i = msg.find("{message: ")
            j = msg.find("} {gql_status")
            detail = msg[i + 10 : j] if i >= 0 and j > i else msg
            print(f"  FAIL  {note:32} -> {detail[:90]}")

    h.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
