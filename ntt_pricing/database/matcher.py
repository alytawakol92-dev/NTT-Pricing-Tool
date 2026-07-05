"""Match extracted components to catalog items.

The matcher blends two signals:

* **Text similarity** between the drawing description and the catalog
  description (RapidFuzz token-set ratio, tolerant of word order and
  abbreviation).
* **Specification agreement** — device type, pole count, current rating and
  breaking capacity parsed from both sides.  This stops "100A MCCB" matching
  a "100A contactor" just because the words overlap.

The final score is a weighted blend, and the top alternatives are retained
so an estimator can review borderline matches.
"""
from __future__ import annotations

from typing import List, Optional

from ..models import CatalogItem, Component, MatchResult, Specification
from .excel_db import ComponentDatabase

try:
    from rapidfuzz import fuzz
    _HAVE_RAPIDFUZZ = True
except Exception:  # pragma: no cover
    import difflib
    _HAVE_RAPIDFUZZ = False


def _text_ratio(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    if _HAVE_RAPIDFUZZ:
        return float(fuzz.token_set_ratio(a.lower(), b.lower()))
    return difflib.SequenceMatcher(None, a.lower(), b.lower()).ratio() * 100.0


def _spec_score(a: Specification, b: Specification) -> float:
    """Return 0..100 agreement between two specifications."""
    score = 0.0
    weight = 0.0

    # device type (heaviest)
    weight += 40
    if a.device_type == b.device_type and a.device_type.name != "UNKNOWN":
        score += 40
    elif a.device_type.name == "UNKNOWN" or b.device_type.name == "UNKNOWN":
        score += 20  # neutral

    # rating amps
    if a.rating_amps and b.rating_amps:
        weight += 30
        rel = abs(a.rating_amps - b.rating_amps) / max(a.rating_amps, b.rating_amps)
        score += 30 * max(0.0, 1.0 - rel * 2.0)  # within 50% still gets partial

    # poles
    if a.poles and b.poles:
        weight += 15
        score += 15 if a.poles == b.poles else 0

    # breaking capacity
    if a.breaking_capacity_ka and b.breaking_capacity_ka:
        weight += 10
        rel = abs(a.breaking_capacity_ka - b.breaking_capacity_ka) / max(
            a.breaking_capacity_ka, b.breaking_capacity_ka)
        score += 10 * max(0.0, 1.0 - rel)

    # curve
    if a.curve and b.curve:
        weight += 5
        score += 5 if a.curve == b.curve else 0

    if weight == 0:
        return 50.0
    return score / weight * 100.0


def match_component(component: Component, db: ComponentDatabase,
                    threshold: float = 60.0, top_n: int = 3,
                    text_weight: float = 0.45) -> Optional[MatchResult]:
    """Find the best catalog match for a single component."""
    query = component.raw_description or component.spec.signature()
    scored: List[MatchResult] = []

    for item in db.items:
        text = _text_ratio(query, f"{item.description} {item.part_number}")
        spec = _spec_score(component.spec, item.spec)
        blended = text_weight * text + (1 - text_weight) * spec
        # a strong exact part-number hit dominates
        if component.raw_description and item.part_number and \
                item.part_number.upper() in component.raw_description.upper():
            blended = max(blended, 97.0)
        scored.append(MatchResult(item=item, score=round(blended, 1),
                                  method="fuzzy"))

    if not scored:
        return None
    scored.sort(key=lambda m: m.score, reverse=True)
    best = scored[0]
    if best.score < threshold:
        best.alternatives = scored[1:top_n]
        best.method = "below-threshold"
        return best  # returned so the estimator can see the near-misses
    best.alternatives = scored[1:top_n]
    return best


def match_all(components: List[Component], db: ComponentDatabase,
              threshold: float = 60.0) -> List[Component]:
    """Attach a :class:`MatchResult` to every component (in place)."""
    for c in components:
        c.match = match_component(c, db, threshold=threshold)
    return components
