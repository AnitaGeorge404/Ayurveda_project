"""
Thin abstraction over "a thing that can run our fixed set of graph
operations". app.main wires up Neo4jGraphStore against the real database.
tests/ wire up FakeGraphStore against an in-memory copy of data/processed/
so the retrieval/evidence/grounding logic can be verified without a live
Neo4j connection.

Neo4j remains the sole source of truth for the running system -- the fake
store exists only for offline unit testing of the logic around it.
"""
import csv
from abc import ABC, abstractmethod
from pathlib import Path

from neo4j import GraphDatabase

from app import config

ROOT = Path(__file__).resolve().parent.parent


class GraphStore(ABC):
    @abstractmethod
    def all_entities(self) -> list[dict]:
        """Return [{name, type, aliases: [..]}] for every node in the graph."""

    @abstractmethod
    def outgoing(self, name: str, predicate: str) -> list[dict]:
        """[{value, value_type, source_file, source_row}] for (name)-[predicate]->()"""

    @abstractmethod
    def incoming(self, name: str, predicate: str) -> list[dict]:
        """[{value, value_type, source_file, source_row}] for ()-[predicate]->(name)"""

    @abstractmethod
    def describe(self, name: str) -> list[dict]:
        """All edges touching `name` in either direction: [{predicate, value, value_type, direction, source_file, source_row}]"""

    @abstractmethod
    def list_by_type(self, node_type: str) -> list[str]:
        """All canonical names of a given node label."""

    @abstractmethod
    def text_corpus(self) -> list[dict]:
        """[{name, type, text}] used for the semantic-retrieval fallback."""


class Neo4jGraphStore(GraphStore):
    def __init__(self):
        self._driver = GraphDatabase.driver(
            config.NEO4J_URI, auth=(config.NEO4J_USERNAME, config.NEO4J_PASSWORD)
        )
        self._database = config.NEO4J_DATABASE

    def close(self):
        self._driver.close()

    def _run(self, query, **params):
        with self._driver.session(database=self._database) as session:
            return [r.data() for r in session.run(query, **params)]

    def all_entities(self) -> list[dict]:
        rows = self._run(
            "MATCH (n) RETURN n.name AS name, labels(n)[0] AS type, "
            "coalesce(n.aliases, []) AS aliases"
        )
        return rows

    def outgoing(self, name: str, predicate: str) -> list[dict]:
        return self._run(
            f"""
            MATCH (s {{name: $name}})-[r:{predicate}]->(o)
            RETURN o.name AS value, labels(o)[0] AS value_type,
                   r.source_file AS source_file, r.source_row AS source_row
            ORDER BY value
            """,
            name=name,
        )

    def incoming(self, name: str, predicate: str) -> list[dict]:
        return self._run(
            f"""
            MATCH (s)-[r:{predicate}]->(o {{name: $name}})
            RETURN s.name AS value, labels(s)[0] AS value_type,
                   r.source_file AS source_file, r.source_row AS source_row
            ORDER BY value
            """,
            name=name,
        )

    def describe(self, name: str) -> list[dict]:
        out = self._run(
            """
            MATCH (s {name: $name})-[r]->(o)
            RETURN type(r) AS predicate, o.name AS value, labels(o)[0] AS value_type,
                   'outgoing' AS direction, r.source_file AS source_file, r.source_row AS source_row
            """,
            name=name,
        )
        inc = self._run(
            """
            MATCH (s)-[r]->(o {name: $name})
            RETURN type(r) AS predicate, s.name AS value, labels(s)[0] AS value_type,
                   'incoming' AS direction, r.source_file AS source_file, r.source_row AS source_row
            """,
            name=name,
        )
        return out + inc

    def list_by_type(self, node_type: str) -> list[str]:
        rows = self._run(f"MATCH (n:{node_type}) RETURN n.name AS name ORDER BY name")
        return [r["name"] for r in rows]

    def text_corpus(self) -> list[dict]:
        rows = self._run(
            "MATCH (n)-[r]->(o) RETURN n.name AS name, labels(n)[0] AS type, "
            "r.source_text AS text"
        )
        return rows


class FakeGraphStore(GraphStore):
    """In-memory store built from data/processed/{nodes,edges}.csv, for tests."""

    def __init__(self, nodes_csv: Path = None, edges_csv: Path = None):
        nodes_csv = nodes_csv or ROOT / "data" / "processed" / "nodes.csv"
        edges_csv = edges_csv or ROOT / "data" / "processed" / "edges.csv"
        self.nodes = {}
        self.edges = []
        with open(nodes_csv, encoding="utf-8") as f:
            for row in csv.DictReader(f):
                aliases = [a for a in row["aliases"].split(";") if a]
                self.nodes[row["canonical_name"]] = {
                    "name": row["canonical_name"],
                    "type": row["node_type"],
                    "aliases": aliases,
                }
        with open(edges_csv, encoding="utf-8") as f:
            for row in csv.DictReader(f):
                self.edges.append(row)

    def all_entities(self) -> list[dict]:
        return list(self.nodes.values())

    def outgoing(self, name, predicate):
        return [
            {"value": e["object_name"], "value_type": e["object_type"],
             "source_file": e["source_file"], "source_row": e["source_row"]}
            for e in self.edges
            if e["subject_name"] == name and e["predicate"] == predicate
        ]

    def incoming(self, name, predicate):
        return [
            {"value": e["subject_name"], "value_type": e["subject_type"],
             "source_file": e["source_file"], "source_row": e["source_row"]}
            for e in self.edges
            if e["object_name"] == name and e["predicate"] == predicate
        ]

    def describe(self, name):
        out = [
            {"predicate": e["predicate"], "value": e["object_name"], "value_type": e["object_type"],
             "direction": "outgoing", "source_file": e["source_file"], "source_row": e["source_row"]}
            for e in self.edges if e["subject_name"] == name
        ]
        inc = [
            {"predicate": e["predicate"], "value": e["subject_name"], "value_type": e["subject_type"],
             "direction": "incoming", "source_file": e["source_file"], "source_row": e["source_row"]}
            for e in self.edges if e["object_name"] == name
        ]
        return out + inc

    def list_by_type(self, node_type):
        return sorted(n["name"] for n in self.nodes.values() if n["type"] == node_type)

    def text_corpus(self):
        return [
            {"name": e["subject_name"], "type": e["subject_type"], "text": e["source_text"]}
            for e in self.edges
        ]
