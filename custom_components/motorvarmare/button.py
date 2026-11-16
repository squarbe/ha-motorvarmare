"""Knappar: kvittera säkerhetsspärr, stoppa forcering."""
from __future__ import annotations

from homeassistant.components.button import ButtonEntity

from .entity import HeaterEntity


async def async_setup_entry(hass, entry, async_add_entities):
    for heater_id, heater in entry.runtime_data.heaters.items():
        async_add_entities(
            [
                AckButton(heater, "acknowledge", "Kvittera spärr"),
                StopForceButton(heater, "stop_force", "Stoppa forcering"),
            ],
            config_subentry_id=heater_id,
        )


class AckButton(HeaterEntity, ButtonEntity):
    _attr_icon = "mdi:shield-check"

    async def async_press(self) -> None:
        await self.heater.async_acknowledge()


class StopForceButton(HeaterEntity, ButtonEntity):
    _attr_icon = "mdi:stop-circle-outline"

    async def async_press(self) -> None:
        await self.heater.async_stop_force()
