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
    CALENDAR_DEFAULTS,
    CALENDAR_SUBENTRY_TYPE,
    CONF_ALLOWED_CALENDARS,
    CONF_AFTER,
    CONF_UNPLUG,
    CONF_AUTO_OFF,
    CONF_CALENDAR,
    CONF_END_DIRECTION,
    CONF_FILTER,
    CONF_HEATER_NOTIFY,
    CONF_HEATERS,
    CONF_KEYWORDS,
    CONF_START_DIRECTION,
    CONF_TRAVEL_END,
    CONF_TRAVEL_START,
    CONF_USE_END,
    CONF_USE_START,
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
    DIRECTION_AFTER,
    DIRECTION_BEFORE,
    DOMAIN,
    FILTER_ALL,
    FILTER_KEYWORD,
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


def _notify_services(hass: Any) -> list[str]:
    return sorted(
        s for s in hass.services.async_services_for_domain("notify")
        if s not in ("send_message", "persistent_notification", "notify")
    )


def _heater_schema(defaults: dict[str, Any], notify_services: list[str]) -> vol.Schema:
    d = {**DEFAULTS, **defaults}
    current = [s for s in d.get(CONF_HEATER_NOTIFY, []) if s in notify_services]
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
            vol.Required(CONF_AFTER, default=d[CONF_AFTER]): _num(0, 120),
            vol.Required(CONF_UNPLUG, default=d[CONF_UNPLUG]): bool,
            vol.Required(CONF_FALLBACK, default=d[CONF_FALLBACK]): _num(0, 360),
            vol.Required(CONF_CACHE, default=d[CONF_CACHE]): _num(0, 1440),
            vol.Optional(CONF_HEATER_NOTIFY, default=current): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[selector.SelectOptionDict(value=s, label=f"notify.{s}") for s in notify_services],
                    multiple=True,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
        }
    )


def _normalize(user_input: dict[str, Any]) -> dict[str, Any]:
    data = dict(user_input)
    for key in (CONF_AUTO_OFF, CONF_BASE, CONF_MIN, CONF_MAX, CONF_AFTER, CONF_FALLBACK, CONF_CACHE):
        data[key] = int(data[key])
    data[CONF_SLOPE] = float(data[CONF_SLOPE])
    if not data.get(CONF_RELAY):
        data.pop(CONF_RELAY, None)
    data[CONF_HEATER_NOTIFY] = list(data.get(CONF_HEATER_NOTIFY) or [])
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
        return {SUBENTRY_TYPE: HeaterSubentryFlow, CALENDAR_SUBENTRY_TYPE: CalendarSubentryFlow}

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return MotorvarmareOptionsFlow()


class MotorvarmareOptionsFlow(OptionsFlow):
    """Integrationens gemensamma inställningar (larmmottagare)."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            value = user_input.get(CONF_NOTIFY, NO_NOTIFY)
            data: dict[str, Any] = {} if value == NO_NOTIFY else {CONF_NOTIFY: value}
            data[CONF_ALLOWED_CALENDARS] = list(user_input.get(CONF_ALLOWED_CALENDARS) or [])
            return self.async_create_entry(data=data)
        services = _notify_services(self.hass)
        options = [selector.SelectOptionDict(value=NO_NOTIFY, label="Ingen (endast avisering i HA)")]
        options += [selector.SelectOptionDict(value=s, label=f"notify.{s}") for s in services]
        current = self.config_entry.options.get(CONF_NOTIFY, NO_NOTIFY)
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_NOTIFY, default=current): selector.SelectSelector(
                        selector.SelectSelectorConfig(options=options, mode=selector.SelectSelectorMode.DROPDOWN)
                    ),
                    vol.Optional(
                        CONF_ALLOWED_CALENDARS,
                        default=list(self.config_entry.options.get(CONF_ALLOWED_CALENDARS, [])),
                    ): selector.EntitySelector(selector.EntitySelectorConfig(domain="calendar", multiple=True)),
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
        count = sum(1 for sub in self._get_entry().subentries.values() if sub.subentry_type == SUBENTRY_TYPE)
        defaults = user_input or {"name": f"Motorvärmare {count + 1}"}
        return self.async_show_form(
            step_id="user", data_schema=_heater_schema(defaults, _notify_services(self.hass)), errors=errors
        )

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
        return self.async_show_form(
            step_id="reconfigure", data_schema=_heater_schema(defaults, _notify_services(self.hass)), errors=errors
        )



def _direction() -> selector.SelectSelector:
    return selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=[DIRECTION_BEFORE, DIRECTION_AFTER],
            translation_key="direction",
            mode=selector.SelectSelectorMode.LIST,
        )
    )


def _calendar_schema(
    defaults: dict[str, Any],
    heater_options: list[selector.SelectOptionDict],
    allowed: list[str],
) -> vol.Schema:
    d = {**CALENDAR_DEFAULTS, **defaults}
    cal_cfg = selector.EntitySelectorConfig(domain="calendar")
    if allowed:
        cal_cfg = selector.EntitySelectorConfig(domain="calendar", include_entities=allowed)
    return vol.Schema(
        {
            vol.Required("name", default=d.get("name", "")): str,
            vol.Required(CONF_CALENDAR, default=d.get(CONF_CALENDAR, vol.UNDEFINED)): selector.EntitySelector(cal_cfg),
            vol.Required(CONF_HEATERS, default=d.get(CONF_HEATERS, [])): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=heater_options, multiple=True, mode=selector.SelectSelectorMode.LIST
                )
            ),
            vol.Required(CONF_FILTER, default=d[CONF_FILTER]): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[FILTER_ALL, FILTER_KEYWORD],
                    translation_key="event_filter",
                    mode=selector.SelectSelectorMode.LIST,
                )
            ),
            vol.Required(CONF_USE_START, default=d[CONF_USE_START]): bool,
            vol.Required(CONF_TRAVEL_START, default=d[CONF_TRAVEL_START]): _num(0, 240),
            vol.Required(CONF_START_DIRECTION, default=d[CONF_START_DIRECTION]): _direction(),
            vol.Required(CONF_USE_END, default=d[CONF_USE_END]): bool,
            vol.Required(CONF_TRAVEL_END, default=d[CONF_TRAVEL_END]): _num(0, 240),
            vol.Required(CONF_END_DIRECTION, default=d[CONF_END_DIRECTION]): _direction(),
        }
    )


class CalendarSubentryFlow(ConfigSubentryFlow):
    """Lägg till eller ändra en kalenderkoppling.

    Steg 1: kalender, uttag, urval och avresetider.
    Steg 2 (bara vid urval "text"): en text per valt uttag. Fälten heter som uttagen.
    """

    _data: dict[str, Any]
    _title: str
    _reconfigure: bool = False

    def _heater_titles(self) -> dict[str, str]:
        return {
            sid: sub.title
            for sid, sub in self._get_entry().subentries.items()
            if sub.subentry_type == SUBENTRY_TYPE
        }

    def _heater_options(self) -> list[selector.SelectOptionDict]:
        return [selector.SelectOptionDict(value=sid, label=title) for sid, title in self._heater_titles().items()]

    def _allowed(self) -> list[str]:
        allowed = list(self._get_entry().options.get(CONF_ALLOWED_CALENDARS) or [])
        if allowed and self._reconfigure:
            # En befintlig koppling ska kunna ändras även om dess kalender har tagits bort ur listan.
            current = self._get_reconfigure_subentry().data.get(CONF_CALENDAR)
            if current and current not in allowed:
                allowed.append(current)
        return allowed

    def _clean(self, user_input: dict[str, Any]) -> tuple[dict[str, Any], dict[str, str]]:
        data = dict(user_input)
        data[CONF_TRAVEL_START] = int(data[CONF_TRAVEL_START])
        data[CONF_TRAVEL_END] = int(data[CONF_TRAVEL_END])
        valid = set(self._heater_titles())
        data[CONF_HEATERS] = [h for h in data.get(CONF_HEATERS, []) if h in valid]
        errors: dict[str, str] = {}
        if not data[CONF_HEATERS]:
            errors[CONF_HEATERS] = "no_heater"
        if not data[CONF_USE_START] and not data[CONF_USE_END]:
            errors[CONF_USE_START] = "no_departure_point"
        if not str(data.get("name", "")).strip():
            errors["name"] = "name_required"
        allowed = self._allowed()
        if allowed and data.get(CONF_CALENDAR) not in allowed:
            errors[CONF_CALENDAR] = "calendar_not_allowed"
        return data, errors

    async def _finish(self) -> SubentryFlowResult:
        if self._reconfigure:
            return self.async_update_and_abort(
                self._get_entry(), self._get_reconfigure_subentry(), title=self._title, data=self._data
            )
        return self.async_create_entry(title=self._title, data=self._data)

    async def _step_main(self, step_id: str, user_input: dict[str, Any] | None, defaults: dict[str, Any]) -> SubentryFlowResult:
        options = self._heater_options()
        errors: dict[str, str] = {}
        if user_input is not None:
            data, errors = self._clean(user_input)
            if not errors:
                self._title = data.pop("name").strip()
                self._data = data
                if data[CONF_FILTER] == FILTER_KEYWORD:
                    return await self.async_step_keywords()
                self._data[CONF_KEYWORDS] = {}
                return await self._finish()
        return self.async_show_form(
            step_id=step_id,
            data_schema=_calendar_schema(user_input or defaults, options, self._allowed()),
            errors=errors,
        )

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        if not self._heater_titles():
            return self.async_abort(reason="no_heaters")
        return await self._step_main("user", user_input, {CONF_HEATERS: list(self._heater_titles())})

    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        self._reconfigure = True
        subentry = self._get_reconfigure_subentry()
        return await self._step_main("reconfigure", user_input, {"name": subentry.title, **subentry.data})

    async def async_step_keywords(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        titles = self._heater_titles()
        chosen = [(hid, titles[hid]) for hid in self._data[CONF_HEATERS]]
        current: dict[str, str] = {}
        if self._reconfigure:
            current = dict(self._get_reconfigure_subentry().data.get(CONF_KEYWORDS) or {})
        errors: dict[str, str] = {}
        if user_input is not None:
            keywords = {
                hid: str(user_input.get(title, "")).strip()
                for hid, title in chosen
                if str(user_input.get(title, "")).strip()
            }
            if not keywords:
                errors["base"] = "no_keyword"
            else:
                self._data[CONF_KEYWORDS] = keywords
                return await self._finish()
        schema = vol.Schema(
            {
                vol.Optional(title, description={"suggested_value": current.get(hid, "")}): str
                for hid, title in chosen
            }
        )
        return self.async_show_form(
            step_id="keywords",
            data_schema=schema,
            errors=errors,
            description_placeholders={"calendar": self._title},
        )
