"""
Step 2/4 of the pipeline: load the normalized, provenance-carrying CSVs
(data/processed/nodes.csv, data/processed/edges.csv) into Neo4j.

Idempotent: uses MERGE throughout, so re-running after a data update is safe
and will not create duplicate nodes/relationships.

Credentials are read only from environment variables (see .env.example) --
never hard-coded here.

Run: python scripts/load_neo4j.py
"""
import csv
import os
from pathlib import Path

from dotenv import load_dotenv
from neo4j import GraphDatabase

ROOT = Path(__file__).resolve().parent.parent
NODES_CSV = ROOT / "data" / "processed" / "nodes.csv"
EDGES_CSV = ROOT / "data" / "processed" / "edges.csv"

load_dotenv(ROOT / ".env")

NEO4J_URI = os.environ["NEO4J_URI"]
NEO4J_USERNAME = os.environ["NEO4J_USERNAME"]
NEO4J_PASSWORD = os.environ["NEO4J_PASSWORD"]
NEO4J_DATABASE = os.environ.get("NEO4J_DATABASE", "neo4j")

CONSTRAINED_LABELS = [
    "Herb", "Category", "Action", "Pathology", "PhysiologicalFunction",
    "Reference", "PharmacologicalConcept", "UnclassifiedPharmacotherapeuticTerm",
    "UnparsedLine",
]


def read_nodes():
    with open(NODES_CSV, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def read_edges():
    with open(EDGES_CSV, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def apply_constraints(session):
    for label in CONSTRAINED_LABELS:
        session.run(
            f"CREATE CONSTRAINT IF NOT EXISTS FOR (n:{label}) REQUIRE n.name IS UNIQUE"
        )


def load_nodes(session, nodes):
    for row in nodes:
        label = row["node_type"]
        aliases = [a for a in row["aliases"].split(";") if a]
        source_files = [s for s in row["source_files"].split(";") if s]
        source_rows = [s for s in row["source_rows"].split(";") if s]
        session.run(
            f"""
            MERGE (n:{label} {{name: $name}})
            SET n.aliases = $aliases,
                n.source_files = $source_files,
                n.source_rows = $source_rows
            """,
            name=row["canonical_name"],
            aliases=aliases,
            source_files=source_files,
            source_rows=source_rows,
        )


def load_edges(session, edges):
    for row in edges:
        query = f"""
        MATCH (s:{row['subject_type']} {{name: $sname}})
        MATCH (o:{row['object_type']} {{name: $oname}})
        MERGE (s)-[r:{row['predicate']} {{
            source_file: $source_file,
            source_row: $source_row,
            source_text: $source_text
        }}]->(o)
        """
        session.run(
            query,
            sname=row["subject_name"],
            oname=row["object_name"],
            source_file=row["source_file"],
            source_row=row["source_row"],
            source_text=row["source_text"],
        )


def main():
    nodes = read_nodes()
    edges = read_edges()

    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USERNAME, NEO4J_PASSWORD))
    driver.verify_connectivity()

    with driver.session(database=NEO4J_DATABASE) as session:
        apply_constraints(session)
        load_nodes(session, nodes)
        load_edges(session, edges)

        counts = session.run(
            "MATCH (n) RETURN labels(n)[0] AS label, count(*) AS c ORDER BY label"
        ).data()
        rel_counts = session.run(
            "MATCH ()-[r]->() RETURN type(r) AS rel, count(*) AS c ORDER BY rel"
        ).data()

    driver.close()

    print(f"Loaded {len(nodes)} node rows, {len(edges)} edge rows.")
    print("Node counts in Neo4j:")
    for row in counts:
        print(f"  {row['label']}: {row['c']}")
    print("Relationship counts in Neo4j:")
    for row in rel_counts:
        print(f"  {row['rel']}: {row['c']}")


if __name__ == "__main__":
    main()
