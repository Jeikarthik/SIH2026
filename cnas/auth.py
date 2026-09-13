"""Role and tier resolution.

Production uses Keycloak. Here a role arrives on a request header and is looked
up in a fixed table. That difference is deliberate and it is not what FR-GOV-1
is about: the requirement is that the *tier* is enforced at the query layer, and
it is - every read in graph.py takes an explicit allowed-tiers list derived
here, server-side, and the client cannot widen it.
"""
from __future__ import annotations

from fastapi import Header, HTTPException

from . import config


class Principal:
    def __init__(self, role: str):
        if role not in config.ROLES:
            raise HTTPException(status_code=401, detail=f"unknown role: {role}")
        self.role = role
        spec = config.ROLES[role]
        self.display: str = spec["display"]
        self.unit: str = spec["unit"]
        self.tiers: list[str] = list(spec["tiers"])

    @property
    def actor(self) -> str:
        return self.display

    def can_see(self, tier: str) -> bool:
        return tier in self.tiers

    def to_dict(self) -> dict:
        return {"role": self.role, "display": self.display,
                "unit": self.unit, "tiers": self.tiers}


def current(x_cnas_role: str = Header(default=config.DEFAULT_ROLE)) -> Principal:
    return Principal(x_cnas_role)
