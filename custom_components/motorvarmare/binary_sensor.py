"""Binära sensorer: värmebehov och säkerhetsspärr."""
from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity

from .entity import HeaterEntity


async def async_setup_entry(hass, entry, async_add_entities):
    for heater_id, heater in entry.runtime_data.heaters.items():
        async_add_entities(
            [NeedSensor(heater, "need", "Värmebehov"), FaultSensor(heater, "fault", "Säkerhetsspärr")],
            config_subentry_id=heater_id,
        )


class NeedSensor(HeaterEntity, BinarySensorEntity):
    _attr_device_class = BinarySensorDeviceClass.HEAT

    @property
    def is_on(self):
        return self.heater.need


class FaultSensor(HeaterEntity, BinarySensorEntity):
    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    @property
    def is_on(self):
        return self.heater.fault

    @property
    def extra_state_attributes(self):
        relay = self.heater.relay
        return {"orsak": relay["fault_reason"], "tidpunkt": relay["fault_at"]}
