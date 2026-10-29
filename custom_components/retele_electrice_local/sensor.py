"""Sensors for Rețele Electrice (McG)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import UnitOfEnergy

from .entity import ReteleElectriceEntity
from .models import ReteleElectriceConfigEntry


def _float(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return None


def _clean_meta(value: Any) -> Any:
    """Remove Salesforce/TIBCO type metadata from attributes."""
    if isinstance(value, dict):
        return {
            key: _clean_meta(item)
            for key, item in value.items()
            if not key.endswith("_type_info")
            and key not in ("field_order_type_info", "apex_schema_type_info")
        }
    if isinstance(value, list):
        return [_clean_meta(item) for item in value]
    return value


def _readings(data: dict) -> list[dict]:
    archive = data.get("archive") or {}
    items = archive.get("XML_Readings") or archive.get("readings") or []
    return items if isinstance(items, list) else []


def _energy_value(reading: dict, energy_type: str) -> float | None:
    meters = reading.get("meter") or []
    if isinstance(meters, dict):
        meters = [meters]
    for meter in meters:
        if str(meter.get("typeofenergy_measured", "")).upper() == energy_type:
            return _float(meter.get("Value"))
    return None


def _latest_reading(data: dict, energy_type: str) -> tuple[dict, float] | None:
    found: list[tuple[datetime, dict, float]] = []
    for reading in _readings(data):
        value = _energy_value(reading, energy_type)
        if value is None:
            continue
        try:
            when = datetime.strptime(reading.get("measureDate", ""), "%d.%m.%Y")
        except (TypeError, ValueError):
            when = datetime.min
        found.append((when, reading, value))
    if not found:
        return None
    _, reading, value = max(found, key=lambda item: item[0])
    return reading, value


def _outage_payload(data: dict) -> dict:
    raw = data.get("outages") or {}
    nested = raw.get("data")
    return nested if isinstance(nested, dict) else raw


def _smart_collection(data: dict) -> list[dict]:
    raw = data.get("smart_meter") or {}
    value = raw.get("queryDailyLoadProfileResponseCollection") or []
    if isinstance(value, dict):
        return [value]
    return value if isinstance(value, list) else []


@dataclass(frozen=True, kw_only=True)
class ReteleSensorDescription(SensorEntityDescription):
    value_fn: Callable[[dict], Any]
    attrs_fn: Callable[[dict], dict[str, Any]] = lambda _data: {}
    exists_fn: Callable[[dict], bool] = lambda _data: True


SENSORS = (
    ReteleSensorDescription(
        key="informatii_pod",
        name="Informații POD",
        icon="mdi:file-document-outline",
        value_fn=lambda data: (data.get("pod_details") or {}).get("activ")
        or "Activ",
        attrs_fn=lambda data: _clean_meta(data.get("pod_details") or {}),
        exists_fn=lambda data: bool(data.get("pod_details")),
    ),
    ReteleSensorDescription(
        key="date_furnizor",
        name="Date furnizor",
        icon="mdi:office-building",
        value_fn=lambda data: (data.get("pod_details") or {}).get("cui")
        or (data.get("pod_details") or {}).get("furnizor")
        or "Disponibil",
        attrs_fn=lambda data: _clean_meta(data.get("pod_details") or {}),
        exists_fn=lambda data: bool(data.get("pod_details")),
    ),
    ReteleSensorDescription(
        key="index_citire_consum",
        name="Index citire consum",
        icon="mdi:counter",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda data: (_latest_reading(data, "EA") or ({}, None))[1],
        attrs_fn=lambda data: _clean_meta(
            (_latest_reading(data, "EA") or ({}, None))[0]
        ),
        exists_fn=lambda data: _latest_reading(data, "EA") is not None,
    ),
    ReteleSensorDescription(
        key="index_citire_productie",
        name="Index citire producție",
        icon="mdi:solar-power",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda data: (_latest_reading(data, "EAP") or ({}, None))[1],
        attrs_fn=lambda data: _clean_meta(
            (_latest_reading(data, "EAP") or ({}, None))[0]
        ),
        exists_fn=lambda data: _latest_reading(data, "EAP") is not None,
    ),
    ReteleSensorDescription(
        key="intreruperi_curent",
        name="Întreruperi curent",
        icon="mdi:flash-alert",
        value_fn=lambda data: (
            "Fără întreruperi"
            if str(_outage_payload(data).get("checkInterruzione", "")).lower()
            in ("true", "1", "ok")
            or str(_outage_payload(data).get("esito", "")).upper() == "OK"
            else "Întrerupere activă"
        ),
        attrs_fn=lambda data: _clean_meta(_outage_payload(data)),
        exists_fn=lambda data: bool(data.get("outages")),
    ),
    ReteleSensorDescription(
        key="smart_meter_consum",
        name="Smart Meter consum",
        icon="mdi:chart-line",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        value_fn=lambda data: _sum_smart(data, "WI"),
        attrs_fn=lambda data: {"înregistrări": len(_smart_collection(data))},
        exists_fn=lambda data: _sum_smart(data, "WI") is not None,
    ),
    ReteleSensorDescription(
        key="smart_meter_productie",
        name="Smart Meter producție",
        icon="mdi:solar-power",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        value_fn=lambda data: _sum_smart(data, "WE"),
        attrs_fn=lambda data: {"înregistrări": len(_smart_collection(data))},
        exists_fn=lambda data: _sum_smart(data, "WE") is not None,
    ),
    ReteleSensorDescription(
        key="valoare_instantanee_consum",
        name="Valoare instantanee consum",
        icon="mdi:flash",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda data: _instant_value(data, ("EA", "activeEnergy", "consumption")),
        attrs_fn=lambda data: _clean_meta(data.get("instant") or {}),
        exists_fn=lambda data: _instant_value(
            data, ("EA", "activeEnergy", "consumption")
        )
        is not None,
    ),
    ReteleSensorDescription(
        key="valoare_instantanee_productie",
        name="Valoare instantanee producție",
        icon="mdi:solar-power",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda data: _instant_value(data, ("EAP", "production")),
        attrs_fn=lambda data: _clean_meta(data.get("instant") or {}),
        exists_fn=lambda data: _instant_value(data, ("EAP", "production"))
        is not None,
    ),
)


def _sum_smart(data: dict, energy_type: str) -> float | None:
    total = 0.0
    found = False
    for row in _smart_collection(data):
        row_type = str(
            row.get("energyType")
            or row.get("type")
            or row.get("commodity")
            or ""
        ).upper()
        if row_type and row_type != energy_type:
            continue
        for key in ("value", "Value", "energy", "quantity", "total"):
            value = _float(row.get(key))
            if value is not None:
                total += value
                found = True
                break
    return total if found else None


def _instant_value(data: dict, keys: tuple[str, ...]) -> float | None:
    raw = data.get("instant") or {}
    if not isinstance(raw, dict):
        return None
    lowered = {str(key).lower(): value for key, value in raw.items()}
    for key in keys:
        value = _float(raw.get(key))
        if value is None:
            value = _float(lowered.get(key.lower()))
        if value is not None:
            return value
    return None


async def async_setup_entry(hass, entry: ReteleElectriceConfigEntry, async_add_entities):
    coordinator = entry.runtime_data.coordinator
    pod = entry.runtime_data.api.pod
    added: set[str] = set()

    def _discover_entities() -> None:
        entities: list[SensorEntity] = []
        for description in SENSORS:
            unique_id = f"{pod}_{description.key}"
            if unique_id in added or not description.exists_fn(coordinator.data):
                continue
            added.add(unique_id)
            entities.append(
                ReteleElectriceSensor(coordinator, pod, description)
            )
        for entity in _annual_entities(coordinator, pod):
            if entity.unique_id in added:
                continue
            added.add(entity.unique_id)
            entities.append(entity)
        if entities:
            async_add_entities(entities)

    _discover_entities()
    entry.async_on_unload(coordinator.async_add_listener(_discover_entities))


def _annual_entities(coordinator, pod: str) -> list["ReteleAnnualSensor"]:
    years: set[tuple[int, str]] = set()
    for reading in _readings(coordinator.data):
        try:
            year = datetime.strptime(reading.get("measureDate", ""), "%d.%m.%Y").year
        except (TypeError, ValueError):
            continue
        for energy_type in ("EA", "EAP"):
            if _energy_value(reading, energy_type) is not None:
                years.add((year, energy_type))
    return [ReteleAnnualSensor(coordinator, pod, year, kind) for year, kind in sorted(years, reverse=True)]


class ReteleElectriceSensor(ReteleElectriceEntity, SensorEntity):
    entity_description: ReteleSensorDescription

    def __init__(self, coordinator, pod: str, description: ReteleSensorDescription) -> None:
        super().__init__(coordinator, pod)
        self.entity_description = description
        self._attr_unique_id = f"{pod}_{description.key}"

    @property
    def native_value(self):
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self):
        return self.entity_description.attrs_fn(self.coordinator.data)


class ReteleAnnualSensor(ReteleElectriceEntity, SensorEntity):
    def __init__(self, coordinator, pod: str, year: int, kind: str) -> None:
        super().__init__(coordinator, pod)
        self.year = year
        self.kind = kind
        suffix = "consumata" if kind == "EA" else "produsa"
        label = "consumată" if kind == "EA" else "produsă"
        self._attr_unique_id = f"{pod}_arhiva_energie_{suffix}_{year}"
        self._attr_name = f"{year} → Energie {label}"
        self._attr_icon = "mdi:history" if kind == "EA" else "mdi:solar-power"
        self._attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR

    @property
    def native_value(self):
        values = self._values()
        if len(values) < 2:
            return 0.0 if values else None
        return round(max(values.values()) - min(values.values()), 3)

    @property
    def extra_state_attributes(self):
        return {key: value for key, value in sorted(self._values().items(), reverse=True)}

    def _values(self) -> dict[str, float]:
        values: dict[str, float] = {}
        for reading in _readings(self.coordinator.data):
            raw_date = reading.get("measureDate", "")
            try:
                parsed = datetime.strptime(raw_date, "%d.%m.%Y")
            except (TypeError, ValueError):
                continue
            if parsed.year != self.year:
                continue
            value = _energy_value(reading, self.kind)
            if value is not None:
                values[raw_date] = value
        return values
