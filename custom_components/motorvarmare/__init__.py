"""Motorvärmare: avresor, temperaturberoende uppvärmning och säker relästyrning."""
from __future__ import annotations

from dataclasses import dataclass, field
import logging
from pathlib import Path
from typing import Any

import voluptuous as vol

from homeassistant.components import persistent_notification
from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device import async_entity_id_to_device
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.storage import Store
from homeassistant.helpers.typing import ConfigType

from .const import (
    CONF_NOTIFY,
    DOMAIN,
    PLATFORMS,
    STORAGE_KEY,
    STORAGE_VERSION,
    SUBENTRY_TYPE,
)
from .heater import Heater, empty_state, parse_departure

_LOGGER = logging.getLogger(__name__)

CARD_URL = "/motorvarmare/motorvarmare-card.js"
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


@dataclass
class RuntimeData:
    store: Store
    data: dict[str, Any]
    heaters: dict[str, Heater] = field(default_factory=dict)


type MotorvarmareConfigEntry = ConfigEntry[RuntimeData]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Registrera tjänster och kortet en gång (oberoende av konfigurationsposten)."""
    _register_services(hass)
    if "http" in hass.config.components and hass.http is not None:
        from homeassistant.components.http import StaticPathConfig

        await hass.http.async_register_static_paths(
            [
                StaticPathConfig(
                    CARD_URL,
                    str(Path(__file__).parent / "frontend" / "motorvarmare-card.js"),
                    False,
                )
            ]
        )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: MotorvarmareConfigEntry) -> bool:
    store: Store = Store(hass, STORAGE_VERSION, STORAGE_KEY)
    data = await store.async_load() or {}
    data.setdefault("heaters", {})
    runtime = RuntimeData(store=store, data=data)
    entry.runtime_data = runtime

    # Ta bort sparat tillstånd för uttag som inte längre finns.
    current = {
        sid for sid, sub in entry.subentries.items() if sub.subentry_type == SUBENTRY_TYPE
    }
    for stale in set(data["heaters"]) - current:
        data["heaters"].pop(stale)

    @callback
    def save() -> None:
        store.async_delay_save(lambda: runtime.data, 2)

    def notify(notification_id: str, title: str, message: str) -> None:
        persistent_notification.async_create(hass, message, title, notification_id)
        service = entry.options.get(CONF_NOTIFY)
        if service and hass.services.has_service("notify", service):
            hass.async_create_task(
                hass.services.async_call(
                    "notify",
                    service,
                    {
                        "title": title,
                        "message": message,
                        "data": {
                            "tag": notification_id,
                            "ttl": 0,
                            "priority": "high",
                            "push": {"interruption-level": "time-sensitive"},
                        },
                    },
                    blocking=False,
                )
            )
        elif service:
            _LOGGER.warning("Notifieringstjänsten notify.%s finns inte", service)

    def dismiss(notification_id: str) -> None:
        persistent_notification.async_dismiss(hass, notification_id)

    for subentry_id in current:
        sub = entry.subentries[subentry_id]
        state = data["heaters"].setdefault(subentry_id, empty_state())
        runtime.heaters[subentry_id] = Heater(
            hass, subentry_id, sub.title, dict(sub.data), state, save, notify, dismiss
        )

    linked: set[str] = set()
    for heater in runtime.heaters.values():
        heater.device_info, is_linked = _device_info(hass, heater)
        if is_linked:
            linked.add(heater.heater_id)

    for heater in runtime.heaters.values():
        await heater.async_start()

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Uttag som nu ligger på reläets enhet ska inte ha kvar en egen tom enhet.
    dev_reg = dr.async_get(hass)
    for device in dr.async_entries_for_config_entry(dev_reg, entry.entry_id):
        own_ids = {ident[1] for ident in device.identifiers if ident[0] == DOMAIN}
        if own_ids and own_ids <= linked:
            dev_reg.async_remove_device(device.id)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


def _device_info(hass: HomeAssistant, heater: Heater) -> tuple[DeviceInfo | dr.DeviceEntry, bool]:
    """Lägg uttagets entiteter på reläets enhet (t.ex. Shellyn) om det går, annars egen enhet.

    Kopplingen görs som HA:s egna hjälpare gör: genom att peka ut enhetsposten
    (device_entry). Reläets enhet döps inte om och får inget nytt område.
    """
    if heater.relay_entity:
        device = async_entity_id_to_device(hass, heater.relay_entity)
        if device is not None:
            return device, True
    return (
        DeviceInfo(
            identifiers={(DOMAIN, heater.heater_id)},
            name=heater.name,
            manufacturer="Egen integration",
            model="Motorvärmaruttag",
        ),
        False,
    )


async def _async_update_listener(hass: HomeAssistant, entry: MotorvarmareConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: MotorvarmareConfigEntry) -> bool:
    ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if ok:
        for heater in entry.runtime_data.heaters.values():
            heater.async_stop()
        await entry.runtime_data.store.async_save(entry.runtime_data.data)
    return ok


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await Store(hass, STORAGE_VERSION, STORAGE_KEY).async_remove()


# ---------------- tjänster ----------------

def _heater(hass: HomeAssistant, call: ServiceCall) -> Heater:
    heater_id = call.data["heater_id"]
    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.state is ConfigEntryState.LOADED and heater_id in entry.runtime_data.heaters:
            return entry.runtime_data.heaters[heater_id]
    raise HomeAssistantError(f"Okänt motorvärmaruttag: {heater_id}")


def _register_services(hass: HomeAssistant) -> None:
    base = {vol.Required("heater_id"): cv.string}

    async def add(call: ServiceCall) -> dict[str, Any]:
        heater = _heater(hass, call)
        trip_id = await heater.async_add_departure(
            parse_departure(call.data["departure_at"]), call.data.get("label", "")
        )
        return {"trip_id": trip_id}

    async def edit(call: ServiceCall) -> None:
        heater = _heater(hass, call)
        when = parse_departure(call.data["departure_at"]) if "departure_at" in call.data else None
        await heater.async_edit_departure(call.data["trip_id"], when, call.data.get("label"))

    async def remove(call: ServiceCall) -> None:
        await _heater(hass, call).async_remove_departure(call.data["trip_id"])

    async def force(call: ServiceCall) -> None:
        await _heater(hass, call).async_force(call.data["minutes"])

    async def stop_force(call: ServiceCall) -> None:
        await _heater(hass, call).async_stop_force()

    async def acknowledge(call: ServiceCall) -> None:
        await _heater(hass, call).async_acknowledge()

    from homeassistant.core import SupportsResponse

    hass.services.async_register(
        DOMAIN,
        "add_departure",
        add,
        schema=vol.Schema(
            {**base, vol.Required("departure_at"): cv.string, vol.Optional("label", default=""): cv.string}
        ),
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        "edit_departure",
        edit,
        schema=vol.Schema(
            {
                **base,
                vol.Required("trip_id"): cv.string,
                vol.Optional("departure_at"): cv.string,
                vol.Optional("label"): cv.string,
            }
        ),
    )
    hass.services.async_register(
        DOMAIN,
        "remove_departure",
        remove,
        schema=vol.Schema({**base, vol.Required("trip_id"): cv.string}),
    )
    hass.services.async_register(
        DOMAIN,
        "force_start",
        force,
        schema=vol.Schema(
            {**base, vol.Optional("minutes", default=60): vol.All(vol.Coerce(int), vol.Range(min=1, max=240))}
        ),
    )
    hass.services.async_register(DOMAIN, "stop_force", stop_force, schema=vol.Schema(base))
    hass.services.async_register(DOMAIN, "acknowledge_fault", acknowledge, schema=vol.Schema(base))
