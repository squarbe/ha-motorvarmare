"""Sensorer. Ingen state_class: inget hamnar i långtidsstatistiken."""
from __future__ import annotations

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.const import UnitOfTime
from homeassistant.util import dt as dt_util

from .entity import HeaterEntity


async def async_setup_entry(hass, entry, async_add_entities):
    for heater_id, heater in entry.runtime_data.heaters.items():
        async_add_entities(
            [
                StatusSensor(heater, "status", "Status"),
                MinutesSensor(heater, "minutes", "Uppvärmningstid"),
                DeparturesSensor(heater, "departures", "Avresor"),
                NextStartSensor(heater, "next_start", "Nästa start"),
            ],
            config_subentry_id=heater_id,
        )


class StatusSensor(HeaterEntity, SensorEntity):
    _attr_icon = "mdi:car-electric"

    @property
    def native_value(self):
        return self.heater.status


class MinutesSensor(HeaterEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.DURATION
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES

    @property
    def native_value(self):
        return self.heater.heating_minutes

    @property
    def extra_state_attributes(self):
        return {
            "temperatur": self.heater.temperature,  # beräkningstemperatur (med hysteres)
            "temperaturkalla": self.heater.temperature_source,
        }


class DeparturesSensor(HeaterEntity, SensorEntity):
    """Antal avresor. Attributen är kortets datakälla och sparas inte av recorder."""

    _attr_icon = "mdi:calendar-clock"
    _unrecorded_attributes = frozenset(
        {
            "trips", "heater_id", "test_mode", "status", "need", "fault", "fault_reason",
            "fault_at", "inhibited", "inhibit_reason", "heating_minutes", "temperature",
            "temperature_source", "next_start", "next_start_preliminary", "force_until",
            "relay_entity",
        }
    )

    @property
    def native_value(self):
        return self.heater.active_trip_count()

    @property
    def extra_state_attributes(self):
        return self.heater.attributes()


class NextStartSensor(HeaterEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    @property
    def native_value(self):
        value = self.heater.next_start()
        return dt_util.as_local(value) if value else None

    @property
    def extra_state_attributes(self):
        return {"preliminar": self.heater.next_start_preliminary}
