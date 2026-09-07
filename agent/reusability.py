"""Reusability scoring: rank assets by how repurposable they are.

Turns each asset's (coarse type, Gemini sub-type, reusable verdict) into a 0-100
reusability score. The library's default view sorts by this score so evergreen,
repurposable material — logos, icons, brand vectors, stock B-roll, music beds —
surfaces at the top, while project-unique assets (voiceovers / dialogue, slates,
rough cuts) sink to the bottom. That is the "sort by reusability" behaviour: what
you can pull into the next project sits above what belongs to exactly one video.
"""
from __future__ import annotations

# Gemini's asset_subtype -> base reusability. Evergreen brand/stock material
# scores high; one-off, project-bound material scores low.
_SUBTYPE_SCORE = {
    "logo": 96, "icon": 93, "vector_art": 90, "b_roll": 88,
    "music": 85, "sfx": 82, "vfx_plate": 68,
    "photo": 55, "document": 32, "screenshot": 22,
    "dialogue": 12,            # voiceovers / on-set dialogue: unique per video
    "other": 45,
}

# Fallback when no subtype was stored (rows ingested before subtype was tracked):
# rank by coarse asset_type so those rows still sort sensibly.
_TYPE_SCORE = {
    "icon": 92, "vector": 88, "video": 62, "audio": 60,
    "image": 55, "document": 32, "other": 45,
}

# A reusable=false verdict caps the score into the "project-specific" band so
# these assets always sort below genuinely repurposable ones.
_UNIQUE_CAP = 28

# Scores at/above this read as "repurposable"; below it, "project-specific". The
# UI draws the divider here.
REUSABLE_BAND = 50


def reusability_score(
    asset_type: str, asset_subtype: str = "", reusable: bool = True
) -> int:
    """A 0-100 reusability score. Higher = more repurposable across projects."""
    if asset_subtype and asset_subtype in _SUBTYPE_SCORE:
        score = _SUBTYPE_SCORE[asset_subtype]
    else:
        score = _TYPE_SCORE.get(asset_type, _TYPE_SCORE["other"])
    if not reusable:
        score = min(score, _UNIQUE_CAP)
    return int(score)


def reusability_sql_expr() -> str:
    """ClickHouse expression matching `reusability_score` for ORDER BY / SELECT.

    Identifiers only — safe to interpolate into a query.
    """
    subtype_cases = ", ".join(
        f"asset_subtype = '{k}', {v}" for k, v in _SUBTYPE_SCORE.items()
    )
    type_cases = ", ".join(
        f"asset_type = '{k}', {v}" for k, v in _TYPE_SCORE.items() if k != "other"
    )
    default = _TYPE_SCORE["other"]
    base = (
        f"multiIf({subtype_cases}, "
        f"multiIf({type_cases}, {default}))"
    )
    return f"if(reusable, {base}, least({base}, {_UNIQUE_CAP}))"
