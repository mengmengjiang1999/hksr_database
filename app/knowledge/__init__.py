"""Evidence-backed entity relations."""

from app.knowledge.relations import (
    audit_relations,
    build_relations,
    list_relations,
    review_relation,
)

from app.knowledge.identity import (
    audit_identity_catalog,
    identity_catalog,
    load_identity_catalog,
    normalize_identity_name,
    replace_identity_catalog,
    resolve_identity_name,
)

__all__ = [
    "audit_identity_catalog", "identity_catalog", "load_identity_catalog",
    "normalize_identity_name", "replace_identity_catalog", "resolve_identity_name",
    "audit_relations", "build_relations",
    "list_relations", "review_relation",
]
