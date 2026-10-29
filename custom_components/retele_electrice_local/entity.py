"""Base entities for Rețele Electrice (McG)."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import ATTRIBUTION, DOMAIN, NAME


class ReteleElectriceEntity(CoordinatorEntity):
    """Base class shared by sensors and buttons."""

    _attr_has_entity_name = True

    def __init__(self, coordinator, pod: str) -> None:
        super().__init__(coordinator)
        self.pod = pod
        self._attr_attribution = ATTRIBUTION
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, pod)},
            name=f"Rețele Electrice {pod}",
            manufacturer="Rețele Electrice România",
            model=NAME,
        )

    @property
    def available(self) -> bool:
        return super().available and bool(self.coordinator.data)
