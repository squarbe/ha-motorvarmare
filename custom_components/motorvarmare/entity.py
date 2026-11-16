"""Gemensam basklass för entiteter."""
from __future__ import annotations

from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.entity import Entity

from .heater import Heater


class HeaterEntity(Entity):
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, heater: Heater, key: str, name: str) -> None:
        self.heater = heater
        self._attr_name = name
        self._attr_unique_id = f"{heater.heater_id}_{key}"
        if isinstance(heater.device_info, dr.DeviceEntry):
            self.device_entry = heater.device_info  # reläets enhet (Shelly)
        else:
            self._attr_device_info = heater.device_info  # egen enhet (uttag utan relä)

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self.heater.subscribe(self.async_write_ha_state))
