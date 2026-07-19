#!/usr/bin/env python3
"""Compatibility layer over the pack-aware workflow resolver.

Adds frontend-only aliases and curated fallbacks for node packs whose current
Manager metadata does not expose an exact class-name mapping.
"""
from __future__ import annotations

import custom_nodes_from_workflow_v2 as resolver


# LiteGraph/ComfyUI frontend note object. It is serialized in workflows but is
# not a backend NODE_CLASS_MAPPINGS entry and must never trigger installation.
resolver.FRONTEND_ONLY.add("Note")


_CURATED_PACKS: dict[str, list[str]] = {
    "MMAudioModelLoader": ["https://github.com/kijai/ComfyUI-MMAudio"],
    "MMAudioSampler": ["https://github.com/kijai/ComfyUI-MMAudio"],
    "MMAudioFeatureUtilsLoader": ["https://github.com/kijai/ComfyUI-MMAudio"],
}

_original_map_candidates = resolver.map_candidates


def map_candidates(mapping, node_type: str) -> list[str]:
    candidates = _original_map_candidates(mapping, node_type)
    if candidates:
        return candidates
    return list(_CURATED_PACKS.get(node_type, []))


resolver.map_candidates = map_candidates


if __name__ == "__main__":
    try:
        raise SystemExit(resolver.main())
    except Exception as exc:
        print(f"workflow custom-node resolver: ERROR: {exc}", file=resolver.sys.stderr)
        raise SystemExit(1)
