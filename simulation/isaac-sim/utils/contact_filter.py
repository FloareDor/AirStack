#!/usr/bin/env python3
"""Pure PhysX contact-body filtering, kept free of omni/carb/pxr imports so
it is importable and unit-testable outside Isaac Sim."""

from __future__ import annotations

from typing import Iterable


def is_own_body(path: str, drone_root: str) -> bool:
    """True if *path* is the drone's own root prim or somewhere under it."""
    root = drone_root.rstrip("/")
    return path == root or path.startswith(root + "/")


def external_contact_bodies(body_paths: Iterable[str], drone_root: str) -> list[str]:
    """Paths in *body_paths* that belong to something other than the drone."""
    return sorted(
        path for path in body_paths if path and not is_own_body(path, drone_root)
    )
