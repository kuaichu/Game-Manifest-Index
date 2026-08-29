"""Approved non-default canonical data domains.

Default Android and PC domains remain derived from the game id.  This small
allowlist only describes domains whose records intentionally share a game and
platform with a default domain.
"""

from __future__ import annotations

from typing import Final


NONDEFAULT_PC_DOMAINS: Final = {
    ("hypergryph", "endfield"): ("endfield-resources",),
}


def nondefault_pc_domains(vendor: str, game_id: str) -> tuple[str, ...]:
    return NONDEFAULT_PC_DOMAINS.get((vendor, game_id), ())


def is_nondefault_pc_domain(vendor: str, game_id: str, domain_id: str) -> bool:
    return domain_id in nondefault_pc_domains(vendor, game_id)


__all__ = ["NONDEFAULT_PC_DOMAINS", "is_nondefault_pc_domain", "nondefault_pc_domains"]
