"""
Step 1 of the pipeline: Excel/text ingestion + data cleaning.

Reads the two raw sources under data/raw/:
  - Category_Medhya.xlsx   (spreadsheet: controlled vocabularies + a curated
                             herb -> physiological/pathological table)
  - relationships_medhya.txt (a Neo4j Cypher-result export, format "n,r,m",
                             pasted by the domain expert; richer relationship
                             coverage: HAS_ACTION, TREATS_PATHOLOGICAL,
                             AFFECTS_PHYSIOLOGICAL, HAS_REFERENCE)

Applies the manually curated normalization map in data/canonical_entities.json
(documented in DATA_CLEANING.md) and writes normalized, provenance-carrying
CSVs to data/processed/. Nothing is discarded silently: every raw vocabulary
term ends up as a node (even with zero relationships) so that "insufficient
evidence" can be distinguished from "unknown entity" at query time.

Run: python scripts/ingest_excel.py
"""
import csv
import json
import re
from pathlib import Path

import openpyxl

ROOT = Path(__file__).resolve().parent.parent
RAW_XLSX = ROOT / "data" / "raw" / "Category_Medhya.xlsx"
RAW_TXT = ROOT / "data" / "raw" / "relationships_medhya.txt"
CANON_MAP = ROOT / "data" / "canonical_entities.json"
OUT_DIR = ROOT / "data" / "processed"

XLSX_FILE_LABEL = "Category_Medhya.xlsx"
TXT_FILE_LABEL = "relationships_medhya.txt"


def load_canon_map():
    with open(CANON_MAP, encoding="utf-8") as f:
        return json.load(f)


def build_alias_index(canon):
    """raw_name (lowercased, stripped) -> (canonical_name, node_type)"""
    idx = {}
    for canonical, aliases in canon["herb_aliases"].items():
        for a in aliases:
            idx[a.strip().lower()] = (canonical, "Herb")
    for canonical, aliases in canon["category_aliases"].items():
        for a in aliases:
            idx[a.strip().lower()] = (canonical, "Category")
    for term in canon["pharmacological_concepts"]:
        idx[term.strip().lower()] = (term, "PharmacologicalConcept")
    for term in canon["misfiled_as_pharmacotherapeutics_actually_physiological_function"]:
        idx[term.strip().lower()] = (term, "PhysiologicalFunction")
    return idx


def norm(s):
    return re.sub(r"\s+", " ", str(s).strip())


class Store:
    """Accumulates deduplicated nodes and edges with provenance."""

    def __init__(self):
        self.nodes = {}   # (node_type, canonical_name) -> {aliases:set, sources:list}
        self.edges = set()  # (subj_type, subj_name, predicate, obj_type, obj_name, source_file, source_row, source_text)

    def add_node(self, node_type, canonical_name, alias=None, source_file=None, source_row=None):
        key = (node_type, canonical_name)
        if key not in self.nodes:
            self.nodes[key] = {"aliases": set(), "sources": []}
        if alias:
            self.nodes[key]["aliases"].add(alias)
        if source_file:
            self.nodes[key]["sources"].append((source_file, source_row))

    def add_edge(self, subj_type, subj_name, predicate, obj_type, obj_name,
                 source_file, source_row, source_text):
        self.edges.add((subj_type, subj_name, predicate, obj_type, obj_name,
                         source_file, source_row, source_text))


def ingest_xlsx(store, alias_idx, canon):
    wb = openpyxl.load_workbook(RAW_XLSX, data_only=True)
    ws = wb["Sheet1"]

    # --- Controlled vocabularies (columns A, B, C) ---
    def col_vals(col):
        vals = []
        for r in range(2, ws.max_row + 1):
            v = ws.cell(row=r, column=col).value
            if v is not None and norm(v):
                vals.append((r, norm(v)))
        return vals

    for row, val in col_vals(2):  # B: Pathological vocabulary
        store.add_node("Pathology", val, source_file=XLSX_FILE_LABEL, source_row=row)

    for row, val in col_vals(1):  # A: Physiological/Functional vocabulary
        store.add_node("PhysiologicalFunction", val, source_file=XLSX_FILE_LABEL, source_row=row)

    for row, val in col_vals(3):  # C: Pharmacotherapeutics vocabulary (mixed -> normalize)
        key = val.strip().lower()
        if key not in alias_idx:
            # Unmapped term encountered: still keep it, flagged, rather than silently dropping.
            store.add_node("UnclassifiedPharmacotherapeuticTerm", val,
                            source_file=XLSX_FILE_LABEL, source_row=row)
            continue
        canonical, node_type = alias_idx[key]
        store.add_node(node_type, canonical, alias=val, source_file=XLSX_FILE_LABEL, source_row=row)

    # --- Curated relationship table (columns F, G, H), rows 3..11 ---
    for r in range(3, ws.max_row + 1):
        herb_raw = ws.cell(row=r, column=6).value
        if herb_raw is None or not norm(herb_raw):
            continue
        herb_raw = norm(herb_raw)
        key = herb_raw.strip().lower()
        subj_canonical, subj_type = alias_idx.get(key, (herb_raw, "UnclassifiedPharmacotherapeuticTerm"))
        store.add_node(subj_type, subj_canonical, alias=herb_raw, source_file=XLSX_FILE_LABEL, source_row=r)

        phys_raw = ws.cell(row=r, column=7).value
        patho_raw = ws.cell(row=r, column=8).value

        for term in (norm(t) for t in str(phys_raw or "").split(",") if norm(t)):
            store.add_node("PhysiologicalFunction", term, source_file=XLSX_FILE_LABEL, source_row=r)
            store.add_edge(subj_type, subj_canonical, "AFFECTS_FUNCTION", "PhysiologicalFunction", term,
                            XLSX_FILE_LABEL, r, f"{herb_raw} | {phys_raw} | {patho_raw}")

        for term in (norm(t) for t in str(patho_raw or "").split(",") if norm(t)):
            store.add_node("Pathology", term, source_file=XLSX_FILE_LABEL, source_row=r)
            store.add_edge(subj_type, subj_canonical, "TREATS_PATHOLOGY", "Pathology", term,
                            XLSX_FILE_LABEL, r, f"{herb_raw} | {phys_raw} | {patho_raw}")


LABEL_TO_TYPE = {
    "Pharmacotherapeutic": None,   # resolved via alias_idx at parse time
    "Action": "Action",
    "Pathological": "Pathology",
    "PhysiologicalFunctional": "PhysiologicalFunction",
    "Reference": "Reference",
}

REL_TO_PREDICATE = {
    "HAS_ACTION": "HAS_ACTION",
    "TREATS_PATHOLOGICAL": "TREATS_PATHOLOGY",
    "AFFECTS_PHYSIOLOGICAL": "AFFECTS_FUNCTION",
    "HAS_REFERENCE": "HAS_REFERENCE",
}

LINE_RE = re.compile(
    r"\(:(?P<slabel>\w+)\s*\{\s*\w+:\s*(?P<sval>[^}]+?)\s*\}\),"
    r"\[:(?P<rel>\w+)\],"
    r"\(:(?P<tlabel>\w+)\s*\{\s*\w+:\s*(?P<tval>[^}]+?)\s*\}\)"
)


def ingest_relationships_txt(store, alias_idx):
    with open(RAW_TXT, encoding="utf-8") as f:
        lines = f.readlines()

    for i, line in enumerate(lines, start=1):
        line = line.strip()
        if not line or line == "n,r,m":
            continue
        m = LINE_RE.match(line)
        if not m:
            store.add_node("UnparsedLine", f"line_{i}", source_file=TXT_FILE_LABEL, source_row=i)
            continue

        sval = norm(m.group("sval"))
        tval = norm(m.group("tval"))
        predicate = REL_TO_PREDICATE.get(m.group("rel"), m.group("rel"))
        tlabel = LABEL_TO_TYPE.get(m.group("tlabel"), m.group("tlabel"))

        key = sval.strip().lower()
        subj_canonical, subj_type = alias_idx.get(key, (sval, "UnclassifiedPharmacotherapeuticTerm"))

        store.add_node(subj_type, subj_canonical, alias=sval, source_file=TXT_FILE_LABEL, source_row=i)
        store.add_node(tlabel, tval, source_file=TXT_FILE_LABEL, source_row=i)
        store.add_edge(subj_type, subj_canonical, predicate, tlabel, tval,
                        TXT_FILE_LABEL, i, line)


def write_outputs(store):
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    nodes_path = OUT_DIR / "nodes.csv"
    with open(nodes_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["node_type", "canonical_name", "aliases", "source_files", "source_rows"])
        for (node_type, name), data in sorted(store.nodes.items()):
            aliases = ";".join(sorted(a for a in data["aliases"] if a.lower() != name.lower()))
            files = ";".join(sorted({s[0] for s in data["sources"]}))
            rows = ";".join(str(s[1]) for s in data["sources"])
            w.writerow([node_type, name, aliases, files, rows])

    edges_path = OUT_DIR / "edges.csv"
    with open(edges_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["subject_type", "subject_name", "predicate", "object_type", "object_name",
                    "source_file", "source_row", "source_text"])
        for e in sorted(store.edges):
            w.writerow(e)

    print(f"Wrote {len(store.nodes)} nodes -> {nodes_path}")
    print(f"Wrote {len(store.edges)} edges -> {edges_path}")

    by_type = {}
    for (node_type, _name) in store.nodes:
        by_type[node_type] = by_type.get(node_type, 0) + 1
    print("Node counts by type:")
    for t, c in sorted(by_type.items()):
        print(f"  {t}: {c}")


def main():
    canon = load_canon_map()
    alias_idx = build_alias_index(canon)
    store = Store()
    ingest_xlsx(store, alias_idx, canon)
    ingest_relationships_txt(store, alias_idx)
    write_outputs(store)


if __name__ == "__main__":
    main()
