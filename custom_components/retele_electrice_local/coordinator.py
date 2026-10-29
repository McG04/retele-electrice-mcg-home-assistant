"""Data coordinator for Rețele Electrice (McG)."""

from __future__ import annotations

from datetime import timedelta
import logging

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import ReteleElectriceError
from .const import NAME

_LOGGER = logging.getLogger(__name__)


class ReteleElectriceCoordinator(DataUpdateCoordinator[dict]):
    """Fetch all portal data at a conservative interval."""

    def __init__(self, hass: HomeAssistant, api, *, scan_interval: int) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=NAME,
            update_interval=timedelta(seconds=scan_interval),
        )
        self.api = api

    async def _async_update_data(self) -> dict:
        try:
            return await self.api.async_fetch_all()
        except ReteleElectriceError as err:
            raise UpdateFailed(str(err)) from err
