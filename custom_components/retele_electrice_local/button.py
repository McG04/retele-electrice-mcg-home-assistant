"""Buttons for Rețele Electrice (McG)."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity

from .entity import ReteleElectriceEntity
from .models import ReteleElectriceConfigEntry


async def async_setup_entry(hass, entry: ReteleElectriceConfigEntry, async_add_entities):
    coordinator = entry.runtime_data.coordinator
    pod = entry.runtime_data.api.pod
    added = False

    def _discover_button() -> None:
        nonlocal added
        smart_available = bool(
            coordinator.data.get("smart_meter") or coordinator.data.get("instant")
        )
        if smart_available and not added:
            added = True
            async_add_entities([ReteleInstantRefreshButton(coordinator, pod)])

    _discover_button()
    entry.async_on_unload(coordinator.async_add_listener(_discover_button))


class ReteleInstantRefreshButton(ReteleElectriceEntity, ButtonEntity):
    _attr_name = "Actualizare valori instantanee"
    _attr_icon = "mdi:refresh"

    def __init__(self, coordinator, pod: str) -> None:
        super().__init__(coordinator, pod)
        self._attr_unique_id = f"{pod}_actualizare_instantanee"

    async def async_press(self) -> None:
        result = await self.coordinator.api.async_refresh_instant()
        self.coordinator.data["instant"] = result
        self.coordinator.async_set_updated_data(self.coordinator.data)
