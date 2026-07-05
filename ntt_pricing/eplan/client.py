"""Retrieve component dimensions from the EPLAN Data Portal.

The EPLAN Data Portal exposes part master data (including the mechanical
envelope) for millions of components.  Access requires an account / API key,
so this client is written defensively:

1. If an API key is configured and the network is reachable, it queries the
   portal for the part and extracts width/height/depth/weight.
2. Every successful lookup is written to a local JSON cache so subsequent
   runs (and offline runs) are instant and reproducible.
3. When neither the API nor the cache can answer, it falls back to a
   physics-based estimator that derives a realistic envelope from the device
   type and current rating (see :mod:`ntt_pricing.eplan.dimensions`).

This layering means the pipeline always produces dimensions, while still
using authoritative data whenever it is available.
"""
from __future__ import annotations

import json
import os
from typing import Dict, Optional

import requests

from ..models import Component, Dimensions
from .dimensions import estimate_dimensions


DEFAULT_PORTAL_URL = "https://dataportal.eplan.com/api"
DEFAULT_CACHE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "data", "eplan_dimensions.json")


class EplanClient:
    def __init__(self, api_key: Optional[str] = None,
                 base_url: str = DEFAULT_PORTAL_URL,
                 cache_path: str = DEFAULT_CACHE,
                 timeout: float = 8.0,
                 offline: bool = False):
        self.api_key = api_key or os.environ.get("EPLAN_API_KEY")
        self.base_url = base_url.rstrip("/")
        self.cache_path = cache_path
        self.timeout = timeout
        self.offline = offline or not self.api_key
        self._cache: Dict[str, dict] = _load_cache(cache_path)
        self._dirty = False

    # ---- public API ----------------------------------------------------
    def get_dimensions(self, component: Component) -> Dimensions:
        """Resolve dimensions for a component, cheapest source first."""
        key = self._cache_key(component)

        cached = self._cache.get(key)
        if cached:
            return Dimensions(source=cached.get("source", "eplan-cache"),
                              **{k: cached[k] for k in
                                 ("width_mm", "height_mm", "depth_mm",
                                  "weight_kg", "din_modules") if k in cached})

        if not self.offline:
            dims = self._query_portal(component)
            if dims is not None:
                self._store(key, dims)
                return dims

        # fall back to the estimator
        dims = estimate_dimensions(component.spec)
        self._store(key, dims, persist=False)  # keep runtime cache only
        return dims

    def flush(self) -> None:
        if self._dirty:
            _save_cache(self.cache_path, self._cache)
            self._dirty = False

    # ---- internals -----------------------------------------------------
    def _cache_key(self, component: Component) -> str:
        pn = None
        if component.match and component.match.item:
            pn = component.match.item.part_number
        return (pn or component.spec.signature() or component.raw_description).upper()

    def _query_portal(self, component: Component) -> Optional[Dimensions]:
        part_number = None
        if component.match and component.match.item:
            part_number = component.match.item.part_number
        if not part_number:
            return None
        try:
            resp = requests.get(
                f"{self.base_url}/parts/search",
                params={"q": part_number},
                headers={"Authorization": f"Bearer {self.api_key}",
                         "Accept": "application/json"},
                timeout=self.timeout,
            )
            if resp.status_code != 200:
                return None
            data = resp.json()
            return _parse_portal_response(data)
        except (requests.RequestException, ValueError):
            return None

    def _store(self, key: str, dims: Dimensions, persist: bool = True) -> None:
        record = {
            "width_mm": dims.width_mm, "height_mm": dims.height_mm,
            "depth_mm": dims.depth_mm, "weight_kg": dims.weight_kg,
            "din_modules": dims.din_modules, "source": dims.source,
        }
        self._cache[key] = record
        if persist:
            self._dirty = True


def _parse_portal_response(data: dict) -> Optional[Dimensions]:
    """Extract the mechanical envelope from an EPLAN part payload.

    The portal returns dimensions under a variety of property names; we look
    for the common ones (millimetres).  Returns ``None`` if nothing usable.
    """
    parts = data.get("parts") or data.get("results") or []
    if not parts:
        return None
    p = parts[0]
    props = {k.lower(): v for k, v in {**p, **p.get("properties", {})}.items()}

    def pick(*names):
        for n in names:
            if n in props and props[n] not in (None, ""):
                try:
                    return float(props[n])
                except (TypeError, ValueError):
                    continue
        return None

    w = pick("width", "width_mm", "b", "mechanicalwidth")
    h = pick("height", "height_mm", "h", "mechanicalheight")
    d = pick("depth", "depth_mm", "t", "mechanicaldepth")
    wt = pick("weight", "weight_kg", "mass") or 0.0
    if not (w and h and d):
        return None
    return Dimensions(width_mm=w, height_mm=h, depth_mm=d,
                      weight_kg=wt, source="eplan-api")


def _load_cache(path: str) -> Dict[str, dict]:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (FileNotFoundError, ValueError):
        return {}


def _save_cache(path: str, cache: Dict[str, dict]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(cache, fh, indent=2, sort_keys=True)
