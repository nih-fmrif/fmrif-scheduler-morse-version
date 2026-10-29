from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from flask import g

Datalist = List[Tuple[str, str]]


def _request_cache_dict(name: str) -> Optional[Dict[Any, Any]]:
    try:
        cache = getattr(g, name)
    except RuntimeError:
        return None
    except AttributeError:
        cache = None
    if cache is None:
        cache = {}
        setattr(g, name, cache)
    return cache


__all__ = ["Datalist", "_request_cache_dict"]
