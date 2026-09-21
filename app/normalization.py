"""
Builds an in-memory alias -> (canonical_name, type) index from whatever the
graph store currently contains, so entity recognition always reflects the
live Neo4j data (source of truth) rather than a separate hard-coded list.
"""
from __future__ import annotations

import re

from app.graph_store import GraphStore


class EntityIndex:
    def __init__(self, store: GraphStore):
        self._alias_to_entity = {}
        self._by_type: dict[str, list[str]] = {}
        for node in store.all_entities():
            name = node["name"]
            node_type = node["type"]
            if not name or not node_type:
                # Defensive: a node without a name/label doesn't belong to our
                # schema at all (e.g. unrelated data sharing the database) --
                # skip it rather than crash the whole index build over it.
                continue
            self._by_type.setdefault(node_type, []).append(name)
            for alias in [name] + list(node.get("aliases", []) or []):
                if not alias:
                    continue
                self._alias_to_entity[alias.strip().lower()] = (name, node_type)

        # Sort candidate surface forms longest-first so multi-word aliases
        # ("Gotu kola", "Sweet flag") are matched before shorter substrings.
        self._surface_forms = sorted(self._alias_to_entity.keys(), key=len, reverse=True)

    def resolve(self, surface_form: str):
        return self._alias_to_entity.get(surface_form.strip().lower())

    def by_type(self, node_type: str) -> list[str]:
        return self._by_type.get(node_type, [])

    def known_names(self) -> set[str]:
        """Every canonical name + alias, lowercased -- used by the grounding validator."""
        return set(self._alias_to_entity.keys())

    def find_in_text(self, text: str) -> list[tuple[str, str]]:
        """Return [(canonical_name, type), ...] for every known entity mentioned in `text`."""
        lower = text.lower()
        found = []
        seen = set()
        for form in self._surface_forms:
            if len(form) < 3:
                continue  # avoid matching short generic aliases as substrings
            pattern = r"(?<![a-z0-9])" + re.escape(form) + r"(?![a-z0-9])"
            if re.search(pattern, lower):
                canonical, node_type = self._alias_to_entity[form]
                key = (canonical, node_type)
                if key not in seen:
                    seen.add(key)
                    found.append(key)
        return found
