"""Runtime models for Rețele Electrice (McG)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TypeAlias

from aiohttp import ClientSession
from homeassistant.config_entries import ConfigEntry

from .api import ReteleElectriceApi
from .coordinator import ReteleElectriceCoordinator


ReteleElectriceConfigEntry: TypeAlias = ConfigEntry["ReteleElectriceRuntimeData"]


@dataclass
class ReteleElectriceRuntimeData:
    """Data kept for one config entry."""

    api: ReteleElectriceApi
    coordinator: ReteleElectriceCoordinator
    session: ClientSession
