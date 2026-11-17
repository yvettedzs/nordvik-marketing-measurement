"""Roles, view access and row-level rules (spec section 4).

Roles are chosen by the caller: there is no login. This is a demo of role-based views, not access control.
"""
from __future__ import annotations

from typing import Any

ALL_VIEWS = ["roas_lenses", "business_health", "attribution_sensitivity", "conversion_lag", "data_quality"]

ROLES: dict[str, dict[str, Any]] = {
    "country_manager_de": {
        "label": "Country Manager, Germany",
        "views": ["business_health", "conversion_lag"],
        "market_lock": "DE",
        "overlay_allowed": False,
    },
    "performance_marketing": {
        "label": "Performance Marketing",
        "views": ["roas_lenses", "attribution_sensitivity", "conversion_lag", "data_quality"],
        "market_lock": None,
        "overlay_allowed": False,
    },
    "leadership": {
        "label": "Marketing Leadership",
        "views": list(ALL_VIEWS),
        "market_lock": None,
        "overlay_allowed": True,
    },
}


class AccessDenied(Exception):
    """Refusal: HTTP 403 with {"error", "access_denied": true}, written to the audit log."""


def get_role(role: str | None) -> dict[str, Any]:
    if role not in ROLES:
        raise AccessDenied(f"Unknown role '{role}'. Valid roles: {', '.join(ROLES)}")
    return ROLES[role]


def check_view(role: str | None, view: str) -> None:
    r = get_role(role)
    if view not in r["views"]:
        raise AccessDenied(f"Role '{role}' ({r['label']}) cannot open view '{view}'. "
                           f"Allowed views: {', '.join(r['views'])}")


def resolve_market(role: str | None, requested: str | None) -> str:
    """Market to use for this role. A locked role gets its market when none is given; any other value is refused."""
    r = get_role(role)
    lock = r["market_lock"]
    if lock is None:
        return "all" if requested is None or str(requested).strip() == "" else str(requested).strip()
    if requested is None or str(requested).strip() == "":
        return lock
    if str(requested).strip().upper() != lock:
        raise AccessDenied(f"Role '{role}' ({r['label']}) is limited to market {lock}; "
                           f"market '{requested}' is refused.")
    return lock


def check_overlay(role: str | None, requested: bool) -> bool:
    """True only for a role that may see the simulated-truth overlay and has switched it on."""
    r = get_role(role)
    if requested and not r["overlay_allowed"]:
        raise AccessDenied(f"Role '{role}' ({r['label']}) cannot switch on the simulated truth overlay "
                           "(validation only); it is limited to leadership.")
    return bool(requested) and r["overlay_allowed"]
