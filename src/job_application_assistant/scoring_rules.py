"""Versioned deterministic policy for documented qualification alignment.

Bump the version whenever weights, classification credit, exclusions, rounding,
or assessment interpretation rules change. Version labels are immutable.
"""

from types import MappingProxyType

SCORING_RULES_VERSION = "documented-alignment-v1"

IMPORTANCE_WEIGHTS = MappingProxyType({"required": 2, "preferred": 1})

# Integer half-credits keep accumulation exact until final rounding.
CLASSIFICATION_HALF_CREDITS = MappingProxyType({
    "strong_match": 2,
    "transferable_experience": 1,
    "evidence_missing": 0,
    "confirmed_gap": 0,
})
