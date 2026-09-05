"""Versioned narrative-person and playable-form identity catalogue for M9."""

from __future__ import annotations

import json
import unicodedata
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Set, Tuple

from app.models.database import Database


NAME_TYPES = {"canonical", "official_alias", "punctuation_variant", "player_shorthand"}
FORM_KINDS = {"base", "alternate"}
LINK_STATUSES = {"approved", "pending", "rejected"}


def load_identity_catalog(path: Path) -> Dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    version = payload.get("schema_version")
    people = payload.get("people")
    if not isinstance(version, int) or version < 1:
        raise ValueError("Identity catalogue requires a positive schema_version")
    if not isinstance(people, list):
        raise ValueError("Identity catalogue requires a people list")
    person_keys: Set[str] = set()
    form_keys: Set[str] = set()
    for person in people:
        key = str(person.get("stable_key", "")).strip()
        if not key or key in person_keys:
            raise ValueError("Narrative people require unique stable keys")
        person_keys.add(key)
        if not str(person.get("canonical_name", "")).strip():
            raise ValueError("Narrative person %s requires canonical_name" % key)
        _validate_names(person.get("names") or [], "person", key)
        for form in person.get("playable_forms") or []:
            form_key = str(form.get("stable_key", "")).strip()
            if not form_key or form_key in form_keys:
                raise ValueError("Playable forms require globally unique stable keys")
            form_keys.add(form_key)
            if form.get("form_kind") not in FORM_KINDS:
                raise ValueError("Playable form %s has invalid form_kind" % form_key)
            if form.get("link_status") not in LINK_STATUSES:
                raise ValueError("Playable form %s has invalid link_status" % form_key)
            if form.get("link_status") == "approved" and not form.get("evidence_id"):
                raise ValueError("Approved playable form %s requires evidence_id" % form_key)
            _validate_names(form.get("names") or [], "form", form_key)
    return payload


def _validate_names(names: Sequence[Mapping[str, Any]], owner_kind: str, owner_key: str) -> None:
    seen = set()
    for item in names:
        name = str(item.get("name", "")).strip()
        name_type = item.get("name_type")
        official = bool(item.get("is_official", False))
        if not name or name in seen:
            raise ValueError("%s %s requires unique non-empty names" % (owner_kind, owner_key))
        seen.add(name)
        if name_type not in NAME_TYPES:
            raise ValueError("Name %s has invalid name_type" % name)
        if name_type == "player_shorthand" and official:
            raise ValueError("Player shorthand %s cannot be official" % name)
        if official and not item.get("evidence_id"):
            raise ValueError("Official name %s requires evidence_id" % name)


def _approved_relation_state(database: Database) -> Set[Tuple[Any, ...]]:
    with database.connect() as connection:
        return {
            (row["id"], row["subject_id"], row["predicate"], row["object_id"], row["evidence_id"])
            for row in connection.execute(
                """SELECT r.id, r.subject_id, r.predicate, r.object_id, re.evidence_id
                   FROM relations r LEFT JOIN relation_evidence re ON re.relation_id = r.id
                   WHERE r.review_status = 'approved' ORDER BY r.id, re.evidence_id"""
            )
        }


def replace_identity_catalog(database: Database, path: Path) -> Dict[str, Any]:
    """Apply the curated identity split atomically without replacing existing entities."""
    payload = load_identity_catalog(path)
    version = int(payload["schema_version"])
    database.initialize()
    evidence_ids = database.evidence_ids()
    for person in payload["people"]:
        names = list(person.get("names") or [])
        for form in person.get("playable_forms") or []:
            names.extend(form.get("names") or [])
        for name in names:
            if bool(name.get("is_official")) and name.get("evidence_id") not in evidence_ids:
                raise ValueError("Official identity name has stale evidence: %s" % name["name"])
    approved_before = _approved_relation_state(database)
    with database.connect() as connection:
        for person in payload["people"]:
            person_key = str(person["stable_key"])
            connection.execute(
                """INSERT INTO narrative_people(stable_key, canonical_name, description, schema_version)
                   VALUES (?, ?, ?, ?) ON CONFLICT(stable_key) DO UPDATE SET
                     canonical_name=excluded.canonical_name, description=excluded.description,
                     schema_version=excluded.schema_version""",
                (person_key, person["canonical_name"], person.get("description", ""), version),
            )
            _replace_names(connection, "person", person_key, person.get("names") or [], version)
            retained_forms = []
            for form in person.get("playable_forms") or []:
                form_key = str(form["stable_key"])
                retained_forms.append(form_key)
                evidence_id = form.get("evidence_id")
                if form["link_status"] == "approved" and evidence_id not in evidence_ids:
                    raise ValueError("Approved form link has stale evidence: %s" % form_key)
                entity_type = str(form.get("entity_type", "playable_form"))
                connection.execute(
                    """INSERT INTO entities(canonical_name, entity_type, description)
                       VALUES (?, ?, ?) ON CONFLICT(canonical_name, entity_type) DO UPDATE SET
                         description=excluded.description""",
                    (form["canonical_name"], entity_type, form.get("description", "")),
                )
                entity_id = int(connection.execute(
                    "SELECT id FROM entities WHERE canonical_name=? AND entity_type=?",
                    (form["canonical_name"], entity_type),
                ).fetchone()[0])
                connection.execute(
                    """INSERT INTO playable_forms(
                         stable_key, narrative_person_key, entity_id, canonical_name, form_kind,
                         link_status, evidence_id, schema_version
                       ) VALUES (?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(stable_key) DO UPDATE SET
                         narrative_person_key=excluded.narrative_person_key,
                         entity_id=excluded.entity_id, canonical_name=excluded.canonical_name,
                         form_kind=excluded.form_kind, link_status=excluded.link_status,
                         evidence_id=excluded.evidence_id, schema_version=excluded.schema_version""",
                    (form_key, person_key, entity_id, form["canonical_name"], form["form_kind"],
                     form["link_status"], evidence_id, version),
                )
                _replace_names(connection, "form", form_key, form.get("names") or [], version)

                # Remove names that previously flattened another playable form into this entity.
                form_names = {item["name"] for item in form.get("names") or []}
                if form["form_kind"] == "alternate":
                    placeholders = ",".join("?" for _ in form_names)
                    if placeholders:
                        connection.execute(
                            "DELETE FROM aliases WHERE entity_id != ? AND alias IN (%s)" % placeholders,
                            (entity_id, *sorted(form_names)),
                        )
                for name in form.get("names") or []:
                    connection.execute(
                        """INSERT INTO aliases(entity_id, alias, alias_type) VALUES (?, ?, ?)
                           ON CONFLICT(entity_id, alias) DO UPDATE SET alias_type=excluded.alias_type""",
                        (entity_id, name["name"],
                         "player" if name["name_type"] == "player_shorthand" else name["name_type"]),
                    )
            if retained_forms:
                placeholders = ",".join("?" for _ in retained_forms)
                connection.execute(
                    "DELETE FROM playable_forms WHERE narrative_person_key=? AND stable_key NOT IN (%s)"
                    % placeholders,
                    (person_key, *retained_forms),
                )
        retained_people = [str(item["stable_key"]) for item in payload["people"]]
        if retained_people:
            placeholders = ",".join("?" for _ in retained_people)
            connection.execute(
                "DELETE FROM narrative_people WHERE stable_key NOT IN (%s)" % placeholders,
                retained_people,
            )
    approved_after = _approved_relation_state(database)
    if approved_before != approved_after:
        raise RuntimeError("Identity migration changed approved relations")
    audit = audit_identity_catalog(database)
    if audit["errors"]:
        raise RuntimeError("Identity migration audit failed: %s" % ", ".join(audit["errors"]))
    return {"schema_version": version, "people": len(payload["people"]),
            "forms": sum(len(item.get("playable_forms") or []) for item in payload["people"]),
            "audit": audit}


def _replace_names(
    connection: Any, owner_kind: str, owner_key: str,
    names: Sequence[Mapping[str, Any]], version: int,
) -> None:
    connection.execute(
        "DELETE FROM identity_names WHERE owner_kind=? AND owner_key=?", (owner_kind, owner_key)
    )
    for item in names:
        connection.execute(
            """INSERT INTO identity_names(
                 owner_kind, owner_key, name, name_type, is_official, evidence_id, schema_version
               ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (owner_kind, owner_key, item["name"], item["name_type"],
             int(bool(item.get("is_official"))), item.get("evidence_id"), version),
        )


def audit_identity_catalog(database: Database) -> Dict[str, Any]:
    database.initialize()
    valid_evidence = database.evidence_ids()
    errors: List[str] = []
    with database.connect() as connection:
        people = [dict(row) for row in connection.execute(
            "SELECT * FROM narrative_people ORDER BY stable_key"
        )]
        forms = [dict(row) for row in connection.execute(
            "SELECT * FROM playable_forms ORDER BY stable_key"
        )]
        names = [dict(row) for row in connection.execute(
            "SELECT * FROM identity_names ORDER BY owner_kind, owner_key, name"
        )]
    person_keys = {row["stable_key"] for row in people}
    form_keys = {row["stable_key"] for row in forms}
    for form in forms:
        if form["narrative_person_key"] not in person_keys:
            errors.append("orphan_form:%s" % form["stable_key"])
        if form["link_status"] == "approved" and form["evidence_id"] not in valid_evidence:
            errors.append("stale_form_evidence:%s" % form["stable_key"])
    for name in names:
        valid_owner = (
            name["owner_key"] in person_keys if name["owner_kind"] == "person"
            else name["owner_key"] in form_keys
        )
        if not valid_owner:
            errors.append("orphan_name:%s" % name["name"])
        if name["name_type"] == "player_shorthand" and bool(name["is_official"]):
            errors.append("player_name_marked_official:%s" % name["name"])
        if bool(name["is_official"]) and name["evidence_id"] not in valid_evidence:
            errors.append("stale_name_evidence:%s" % name["name"])
    return {"people": len(people), "forms": len(forms), "names": len(names),
            "approved_links": sum(row["link_status"] == "approved" for row in forms),
            "pending_links": sum(row["link_status"] == "pending" for row in forms),
            "errors": sorted(set(errors))}


def identity_catalog(database: Database, *, include_pending: bool = False) -> List[Dict[str, Any]]:
    """Return people with distinct forms; pending links are hidden by default."""
    audit = audit_identity_catalog(database)
    if audit["errors"]:
        raise RuntimeError("Identity catalogue is invalid")
    with database.connect() as connection:
        people = [dict(row) for row in connection.execute(
            "SELECT * FROM narrative_people ORDER BY canonical_name"
        )]
        forms = [dict(row) for row in connection.execute(
            """SELECT * FROM playable_forms ORDER BY narrative_person_key,
               CASE form_kind WHEN 'base' THEN 0 ELSE 1 END, canonical_name"""
        )]
        names = [dict(row) for row in connection.execute(
            "SELECT * FROM identity_names ORDER BY owner_kind, owner_key, name_type, name"
        )]
    names_by_owner: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
    for name in names:
        names_by_owner.setdefault((name["owner_kind"], name["owner_key"]), []).append(name)
    output = []
    for person in people:
        visible_forms = [
            {**form, "names": names_by_owner.get(("form", form["stable_key"]), [])}
            for form in forms if form["narrative_person_key"] == person["stable_key"]
            and (include_pending or form["link_status"] == "approved")
        ]
        output.append({**person, "names": names_by_owner.get(("person", person["stable_key"]), []),
                       "playable_forms": visible_forms})
    return output


def normalize_identity_name(value: str) -> str:
    """Normalize typography while preserving the semantic words in a form name."""
    value = unicodedata.normalize("NFKC", value).strip().lower().replace("•", "·")
    return "".join(character for character in value if not character.isspace())


def resolve_identity_name(
    database: Database, name: str, *, expand_person: bool = False,
    include_pending: bool = False,
) -> Dict[str, Any]:
    """Resolve an exact typed name and optionally expand through its narrative person."""
    target = normalize_identity_name(name)
    people = identity_catalog(database, include_pending=include_pending)
    matches = []
    for person in people:
        for typed_name in person["names"]:
            if normalize_identity_name(typed_name["name"]) == target:
                matches.append({"owner_kind": "person", "owner": person,
                                "typed_name": typed_name, "person": person})
        for form in person["playable_forms"]:
            for typed_name in form["names"]:
                if normalize_identity_name(typed_name["name"]) == target:
                    matches.append({"owner_kind": "form", "owner": form,
                                    "typed_name": typed_name, "person": person})
    matches.sort(key=lambda item: (
        0 if item["typed_name"]["name"] == name else 1,
        0 if item["owner_kind"] == "form" else 1,
        0 if item["typed_name"]["name_type"] == "canonical" else 1,
        item["owner"]["stable_key"],
    ))
    if not matches:
        return {"status": "not_found", "query": name, "matches": [], "expanded_forms": []}
    selected = matches[0]
    expanded = []
    if expand_person:
        expanded = [
            {"stable_key": form["stable_key"], "canonical_name": form["canonical_name"],
             "link_status": form["link_status"]}
            for form in selected["person"]["playable_forms"]
        ]
    return {
        "status": "resolved",
        "query": name,
        "match_kind": selected["owner_kind"],
        "matched_name": selected["typed_name"]["name"],
        "name_type": selected["typed_name"]["name_type"],
        "is_official": bool(selected["typed_name"]["is_official"]),
        "narrative_person": {
            "stable_key": selected["person"]["stable_key"],
            "canonical_name": selected["person"]["canonical_name"],
        },
        "playable_form": (
            {"stable_key": selected["owner"]["stable_key"],
             "canonical_name": selected["owner"]["canonical_name"],
             "link_status": selected["owner"]["link_status"]}
            if selected["owner_kind"] == "form" else None
        ),
        "matches": [{"owner_kind": item["owner_kind"],
                     "stable_key": item["owner"]["stable_key"]} for item in matches],
        "expanded_forms": expanded,
    }
