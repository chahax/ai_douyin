"""Versioned registry for domain strategy plugins."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

from src.operations_accounts import AccountProfile

from .base import DomainStrategy


_SAFE_ID = re.compile(r"^[a-z][a-z0-9_]{1,63}$")
_SAFE_VERSION = re.compile(r"^v[0-9]+(?:\.[0-9]+){0,2}$")


@dataclass(frozen=True, slots=True)
class DomainStrategySpec:
    strategy_id: str
    version: str
    label: str
    config_schema: dict


class DomainStrategyRegistry:
    def __init__(self) -> None:
        self._strategies: dict[tuple[str, str], DomainStrategy] = {}

    def register(self, strategy: DomainStrategy) -> None:
        if not isinstance(strategy, DomainStrategy):
            raise TypeError("domain strategy does not implement the required contract")
        if not _SAFE_ID.fullmatch(strategy.strategy_id):
            raise ValueError(f"invalid domain strategy id: {strategy.strategy_id!r}")
        if not _SAFE_VERSION.fullmatch(strategy.version):
            raise ValueError(f"invalid domain strategy version: {strategy.version!r}")
        key = (strategy.strategy_id, strategy.version)
        if key in self._strategies:
            raise ValueError(
                f"duplicate domain strategy: {strategy.strategy_id}/{strategy.version}"
            )
        schema = strategy.config_schema()
        if not isinstance(schema, dict) or schema.get("type") != "object":
            raise ValueError("domain strategy config_schema must describe an object")
        self._strategies[key] = strategy

    def get(self, strategy_id: str, version: str) -> DomainStrategy:
        try:
            return self._strategies[(strategy_id, version)]
        except KeyError as exc:
            raise KeyError(f"unknown domain strategy: {strategy_id}/{version}") from exc

    def resolve(self, profile: AccountProfile) -> DomainStrategy:
        if profile.status != "active":
            raise ValueError(
                f"account profile {profile.account_key!r} is not active: {profile.status}"
            )
        strategy = self.get(*profile.strategy_key)
        strategy.validate_profile(profile)
        return strategy

    def list_available(self) -> list[DomainStrategySpec]:
        return [
            DomainStrategySpec(
                strategy_id=strategy.strategy_id,
                version=strategy.version,
                label=strategy.label,
                config_schema=strategy.config_schema(),
            )
            for _, strategy in sorted(self._strategies.items())
        ]


def register_many(
    registry: DomainStrategyRegistry,
    strategies: Iterable[DomainStrategy],
) -> DomainStrategyRegistry:
    for strategy in strategies:
        registry.register(strategy)
    return registry
