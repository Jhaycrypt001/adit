"""Does the engine support TWO chained reverse hops from one fixed anchor?

Confirmed earlier: single reverse hop works, two forward hops work, transitive
reverse (with *) is rejected. Never tested: two *fixed* (non-variable-length)
reverse hops chained together, which is exactly the shape
`(rel {id: X})<-[:OBJECT]-(f)<-[:SUBJECT]-(s)` needs for exposed_services.
"""

from __future__ import annotations

from adit.graph import Hydra

FORMS = [
    ("two chained reverse hops, one MATCH",
     "MATCH (rel {id: 8000003})<-[:OBJ]-(f)<-[:SUBJ]-(s) RETURN s.key AS key"),
    ("two chained reverse hops, split MATCH",
     "MATCH (rel {id: 8000003}) MATCH (rel)<-[:OBJ]-(f) MATCH (f)<-[:SUBJ]-(s) RETURN s.key AS key"),
    ("reverse then forward",
     "MATCH (rel {id: 8000003})<-[:OBJ]-(f)-[:SUBJ]->(s) RETURN s.key AS key"),
    ("bind f first (control)",
     "MATCH (rel {id: 8000003})<-[:OBJ]-(f) RETURN f.key AS key"),
    ("from f forward to s (control)",
     "MATCH (f {id: 8000002})-[:SUBJ]->(s) RETURN s.key AS key"),
]


def main() -> int:
    h = Hydra()
    h.verify()
    h.run("CREATE (s {id: 8000001, key: 'svc'})<-[:SUBJ]-(f {id: 8000002, key: 'fact'})")
    h.run("CREATE (f {id: 8000002})-[:OBJ]->(rel {id: 8000003, key: 'rel'})")

    for note, cypher in FORMS:
        try:
            rows = h.run(cypher)
            print(f"  PASS  {note:34} -> {[r.get('key') for r in rows]}")
        except Exception as exc:  # noqa: BLE001
            msg = str(exc)
            i, j = msg.find("{message: "), msg.find("} {gql_status")
            print(f"  FAIL  {note:34} -> {msg[i+10:j] if i>=0<j else msg[:100]}")

    h.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
