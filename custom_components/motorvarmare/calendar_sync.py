"""Kalenderkopplingar: läser händelser ur en kalender i HA och gör dem till avresor.

Varje kalenderkoppling (underpost "kalender") anger
  - kalendern (t.ex. en Google-kalender som redan finns i HA),
  - vilka uttag avresorna gäller,
  - om händelsens start ger en avresa, och restiden före start,
  - om händelsens slut ger en avresa, och restiden före slut.

Alla händelser med klockslag blir avresor. Heldagshändelser ignoreras.
Läsningen görs med tjänsten calendar.get_events, var 5:e minut och när
kalenderentiteten ändras. Misslyckas läsningen behålls tidigare avresor.
"""
from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
import hashlib
import logging
from typing import Any

from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.event import (
    async_track_state_change_event,
    async_track_time_interval,
)
from homeassistant.util import dt as dt_util

from .const import (
    CALENDAR_DEFAULTS,
    CALENDAR_LOOKAHEAD,
    CALENDAR_LOOKBACK,
    CALENDAR_REFRESH,
    CONF_CALENDAR,
    CONF_HEATERS,
    CONF_TRAVEL_END,
    CONF_TRAVEL_START,
    CONF_USE_END,
    CONF_USE_START,
)
from .heater import Heater

_LOGGER = logging.getLogger(__name__)


def _event_time(value: Any) -> datetime | None:
    """Tolka start/slut från get_events. Datum utan klockslag (heldag) ger None."""
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value)
        if "T" not in text and " " not in text:
            return None  # heldagshändelse
        parsed = dt_util.parse_datetime(text)
        if parsed is None:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt_util.get_default_time_zone())
    return dt_util.as_utc(parsed)


def departures_from_events(
    source_id: str, config: dict[str, Any], events: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Räkna fram avresor (UTC) ur kalenderhändelser enligt kopplingens inställningar."""
    cfg = {**CALENDAR_DEFAULTS, **config}
    result: list[dict[str, Any]] = []
    for event in events:
        start = _event_time(event.get("start"))
        end = _event_time(event.get("end"))
        if start is None:
            continue
        summary = str(event.get("summary") or "").strip() or "Kalenderhändelse"
        base = f"{source_id}|{start.isoformat()}|{end.isoformat() if end else ''}|{summary}"
        if cfg[CONF_USE_START]:
            result.append(
                {
                    "id": "k" + hashlib.sha1(f"{base}|start".encode()).hexdigest()[:11],
                    "departure_at": start - timedelta(minutes=int(cfg[CONF_TRAVEL_START])),
                    "label": summary,
                }
            )
        if cfg[CONF_USE_END] and end is not None:
            result.append(
                {
                    "id": "k" + hashlib.sha1(f"{base}|end".encode()).hexdigest()[:11],
                    "departure_at": end - timedelta(minutes=int(cfg[CONF_TRAVEL_END])),
                    "label": f"{summary} (slut)",
                }
            )
    return result


class CalendarSource:
    """En kalenderkoppling."""

    def __init__(
        self,
        hass: HomeAssistant,
        source_id: str,
        name: str,
        config: dict[str, Any],
        heaters: dict[str, Heater],
    ) -> None:
        self.hass = hass
        self.source_id = source_id
        self.name = name
        self.config = {**CALENDAR_DEFAULTS, **config}
        self.heaters = heaters
        self.last_error: str | None = None
        self.last_read: datetime | None = None
        self._unsubs: list[Callable[[], None]] = []

    @property
    def calendar_entity(self) -> str:
        return self.config[CONF_CALENDAR]

    def targets(self) -> list[Heater]:
        return [self.heaters[h] for h in self.config.get(CONF_HEATERS, []) if h in self.heaters]

    async def async_start(self) -> None:
        self._unsubs.append(
            async_track_state_change_event(self.hass, [self.calendar_entity], self._on_state)
        )
        self._unsubs.append(async_track_time_interval(self.hass, self._on_tick, CALENDAR_REFRESH))
        self.hass.async_create_task(self.async_refresh())

    @callback
    def async_stop(self) -> None:
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()

    @callback
    def _on_state(self, event: Event) -> None:
        self.hass.async_create_task(self.async_refresh())

    async def _on_tick(self, _now: datetime) -> None:
        await self.async_refresh()

    async def async_refresh(self) -> None:
        now = dt_util.utcnow()
        try:
            response = await self.hass.services.async_call(
                "calendar",
                "get_events",
                {
                    "entity_id": self.calendar_entity,
                    "start_date_time": dt_util.as_local(now - CALENDAR_LOOKBACK).isoformat(),
                    "end_date_time": dt_util.as_local(now + CALENDAR_LOOKAHEAD).isoformat(),
                },
                blocking=True,
                return_response=True,
            )
            events = (response or {}).get(self.calendar_entity, {}).get("events", [])
        except Exception as err:  # noqa: BLE001
            # Kalendern kan vara otillgänglig (t.ex. direkt efter omstart): behåll tidigare avresor.
            if self.last_error != str(err):
                _LOGGER.warning("%s: kunde inte läsa %s: %s", self.name, self.calendar_entity, err)
            self.last_error = str(err)
            return
        self.last_error = None
        self.last_read = now
        departures = departures_from_events(self.source_id, self.config, events)
        for heater in self.targets():
            await heater.async_sync_calendar(self.source_id, self.name, departures)
