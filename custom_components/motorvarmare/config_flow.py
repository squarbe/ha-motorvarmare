"""Konfigurationsflöden: en integration, ett uttag per underpost."""
from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    ConfigSubentryFlow,
    OptionsFlow,
    SubentryFlowResult,
)
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    CONF_AUTO_OFF,
    CONF_BASE,
    CONF_CACHE,
    CONF_FALLBACK,
    CONF_LIVE,
    CONF_MAX,
    CONF_MIN,
    CONF_NOTIFY,
    CONF_RELAY,
    CONF_SLOPE,
    CONF_TEMPERATURE,
    DEFAULTS,
    DOMAIN,
    SUBENTRY_TYPE,
)

NO_NOTIFY = "__ingen__"


def _num(minimum: float, maximum: float, step: float = 1, unit: str = "min") -> selector.NumberSelector:
    return selector.NumberSelector(
        selector.NumberSelectorConfig(
            min=minimum, max=maximum, step=step, unit_of_measurement=unit,
            mode=selector.NumberSelectorMode.BOX,
        )
    )


def _heater_schema(defaults: dict[str, Any]) -> vol.Schema:
    d = {**DEFAULTS, **defaults}
    relay_key = (
        vol.Optional(CONF_RELAY, description={"suggested_value": d.get(CONF_RELAY)})
    )
    return vol.Schema(
        {
            vol.Required("name", default=d.get("name", "Motorvärmare 1")): str,
            vol.Required(CONF_TEMPERATURE, default=d.get(CONF_TEMPERATURE, vol.UNDEFINED)): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor", device_class="temperature")
            ),
            relay_key: selector.EntitySelector(selector.EntitySelectorConfig(domain="switch")),
            vol.Required(CONF_LIVE, default=d[CONF_LIVE]): bool,
            vol.Required(CONF_AUTO_OFF, default=d[CONF_AUTO_OFF]): _num(15, 1440),
            vol.Required(CONF_BASE, default=d[CONF_BASE]): _num(0, 360),
            vol.Required(CONF_SLOPE, default=d[CONF_SLOPE]): _num(0, 20, 0.1, "min/°C"),
            vol.Required(CONF_MIN, default=d[CONF_MIN]): _num(0, 360),
            vol.Required(CONF_MAX, default=d[CONF_MAX]): _num(0, 360),
            vol.Required(CONF_FALLBACK, default=d[CONF_FALLBACK]): _num(0, 360),
            vol.Required(CONF_CACHE, default=d[CONF_CACHE]): _num(0, 1440),
        }
    )


def _normalize(user_input: dict[str, Any]) -> dict[str, Any]:
    data = dict(user_input)
    for key in (CONF_AUTO_OFF, CONF_BASE, CONF_MIN, CONF_MAX, CONF_FALLBACK, CONF_CACHE):
        data[key] = int(data[key])
    data[CONF_SLOPE] = float(data[CONF_SLOPE])
    if not data.get(CONF_RELAY):
        data.pop(CONF_RELAY, None)
    return data


class MotorvarmareConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 2

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(title="Motorvärmare", data={})
        return self.async_show_form(step_id="user", data_schema=vol.Schema({}))

    @classmethod
    @callback
    def async_get_supported_subentry_types(cls, config_entry: ConfigEntry) -> dict[str, type[ConfigSubentryFlow]]:
        return {SUBENTRY_TYPE: HeaterSubentryFlow}

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return MotorvarmareOptionsFlow()


class MotorvarmareOptionsFlow(OptionsFlow):
    """Integrationens gemensamma inställningar (larmmottagare)."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            value = user_input.get(CONF_NOTIFY, NO_NOTIFY)
            return self.async_create_entry(data={} if value == NO_NOTIFY else {CONF_NOTIFY: value})
        services = sorted(
            s for s in self.hass.services.async_services_for_domain("notify")
            if s not in ("send_message", "persistent_notification", "notify")
        )
        options = [selector.SelectOptionDict(value=NO_NOTIFY, label="Ingen (endast avisering i HA)")]
        options += [selector.SelectOptionDict(value=s, label=f"notify.{s}") for s in services]
        current = self.config_entry.options.get(CONF_NOTIFY, NO_NOTIFY)
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_NOTIFY, default=current): selector.SelectSelector(
                        selector.SelectSelectorConfig(options=options, mode=selector.SelectSelectorMode.DROPDOWN)
                    )
                }
            ),
        )


class HeaterSubentryFlow(ConfigSubentryFlow):
    """Lägg till eller ändra ett motorvärmaruttag."""

    def _validate(self, data: dict[str, Any], own_id: str | None) -> dict[str, str]:
        errors: dict[str, str] = {}
        if data[CONF_MIN] > data[CONF_MAX]:
            errors[CONF_MIN] = "min_over_max"
        if data[CONF_LIVE] and not data.get(CONF_RELAY):
            errors[CONF_LIVE] = "live_needs_relay"
        if data.get(CONF_RELAY):
            for sid, sub in self._get_entry().subentries.items():
                if sid != own_id and sub.data.get(CONF_RELAY) == data[CONF_RELAY]:
                    errors[CONF_RELAY] = "relay_in_use"
        if data[CONF_AUTO_OFF] < 15:
            errors[CONF_AUTO_OFF] = "auto_off_too_short"
        return errors

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            data = _normalize(user_input)
            errors = self._validate(data, None)
            if not errors:
                name = data.pop("name")
                return self.async_create_entry(title=name, data=data)
        defaults = user_input or {"name": f"Motorvärmare {len(self._get_entry().subentries) + 1}"}
        return self.async_show_form(step_id="user", data_schema=_heater_schema(defaults), errors=errors)

    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        subentry = self._get_reconfigure_subentry()
        errors: dict[str, str] = {}
        if user_input is not None:
            data = _normalize(user_input)
            errors = self._validate(data, subentry.subentry_id)
            if not errors:
                name = data.pop("name")
                return self.async_update_and_abort(self._get_entry(), subentry, title=name, data=data)
        defaults = user_input or {"name": subentry.title, **subentry.data}
        return self.async_show_form(step_id="reconfigure", data_schema=_heater_schema(defaults), errors=errors)
