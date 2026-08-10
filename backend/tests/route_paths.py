"""Route introspection that survives FastAPI's `include_router` rewrite.

`requirements.txt` pins FastAPI 0.111, where `include_router` copies every
endpoint straight onto `app.routes`. Newer releases (0.14x) instead put one
`_IncludedRouter` wrapper per call on `app.routes` and keep the endpoints on
`wrapper.original_router`. A flat `{r.path for r in app.routes}` therefore
raises `AttributeError` on the wrapper and silently sees no endpoints at all.

These helpers walk through the wrapper so the route assertions hold on both
versions.
"""
from __future__ import annotations

from collections.abc import Iterator
from typing import Any


def iter_route_paths(app: Any) -> Iterator[tuple[str, frozenset[str]]]:
    """Yield `(path, methods)` for every endpoint reachable from `app`."""
    yield from _walk(getattr(app, "routes", app), "")


def route_paths(app: Any) -> set[str]:
    return {path for path, _methods in iter_route_paths(app)}


def route_signatures(app: Any) -> set[tuple[str, str]]:
    """`{(path, "GET,POST")}` — the shape the API contract test compares."""
    return {
        (path, ",".join(sorted(methods)))
        for path, methods in iter_route_paths(app)
    }


def _walk(routes: Any, prefix: str) -> Iterator[tuple[str, frozenset[str]]]:
    for route in routes:
        included = getattr(route, "original_router", None)
        if included is not None:
            context = getattr(route, "include_context", None)
            nested = getattr(context, "prefix", "") or ""
            yield from _walk(included.routes, prefix + nested)
            continue
        path = getattr(route, "path", None)
        if path is not None:
            yield prefix + path, frozenset(getattr(route, "methods", None) or ())
            continue
        # Mounts and sub-applications: keep descending, they carry no path here.
        nested_routes = getattr(route, "routes", None)
        if nested_routes:
            yield from _walk(nested_routes, prefix)
