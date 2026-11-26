"""Logik för ett motorvärmaruttag: avresor, värmebehov och säker relästyrning.

Säkerhetsinvarianter (live-läge):
  S1  Integrationen skickar aldrig PÅ medan säkerhetsspärr är aktiv.
  S2  Ett relä som integrationen beordrat PÅ, och som sedan rapporteras AV i minst
      30 s i följd utan att integrationen beordrat AV, ger säkerhetsspärr + larm.
      Reläet återinkopplas inte.
  S3  Efter omstart/omladdning: om senaste kommando var PÅ och reläet är AV,
      återinkopplas det aldrig automatiskt. Spärr + larm om frånslaget inte kan
      förklaras av maxtiden; annars spärras resten av behovsperioden utan larm.
  S4  Integrationen slår själv av reläet 5 min före Shellyns Auto Off, och slår inte
      på igen under samma behovsperiod. Auto Off ska alltså aldrig behöva lösa ut.
  S5  Kvittering av spärr startar aldrig reläet. Ny inkoppling kräver en ny
      behovsperiod (behovet har varit AV) eller en uttrycklig forcerad start.
  S6  Otillgängligt relä är inte AV: inga kommandon skickas, varning efter 2 min.
"""
from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime, timedelta
import logging
import math
from typing import Any
import uuid

from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.event import (
    async_track_state_change_event,
    async_track_time_interval,
)
from homeassistant.util import dt as dt_util

from .const import (
    EXACT_WINDOW,
    PRELIM_HORIZON,
    PRELIM_REFRESH,
    PRELIM_TEMP_JUMP,
    TEMP_HYSTERESIS,
    CONF_AFTER,
    AUTO_OFF_MARGIN,
    CONF_AUTO_OFF,
    CONF_BASE,
    CONF_CACHE,
    CONF_FALLBACK,
    CONF_LIVE,
    CONF_MAX,
    CONF_MIN,
    CONF_RELAY,
    CONF_SLOPE,
    CONF_TEMPERATURE,
    DEFAULTS,
    RELAY_CONFIRM,
    TEMP_VALID,
    TICK,
    UNAVAILABLE_WARN,
)

_LOGGER = logging.getLogger(__name__)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _dt(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = dt_util.parse_datetime(value)
    return dt_util.as_utc(parsed) if parsed else None


def parse_departure(value: Any) -> datetime:
    """Tolka avresetid. Tid utan tidszon tolkas som lokal tid i HA."""
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = dt_util.parse_datetime(str(value).strip())
    if parsed is None:
        raise HomeAssistantError(f"Ogiltig avresetid: {value}")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt_util.get_default_time_zone())
    return dt_util.as_utc(parsed)


def empty_state() -> dict[str, Any]:
    return {
        "trips": [],
        "force_until": None,
        "last_temperature": None,
        "last_temperature_at": None,
        "relay": {
            "commanded": None,  # None | "on" | "off"
            "commanded_at": None,
            "on_at": None,  # när nuvarande PÅ-period började (för maxtid)
            "confirmed": False,  # reläet har rapporterat PÅ efter PÅ-kommandot
            "fault": False,
            "fault_reason": None,
            "fault_at": None,
            "inhibited": False,  # ingen automatisk inkoppling resten av behovsperioden
            "inhibit_reason": None,
        },
    }


class Heater:
    """Ett motorvärmaruttag."""

    def __init__(
        self,
        hass: HomeAssistant,
        heater_id: str,
        name: str,
        config: dict[str, Any],
        state: dict[str, Any],
        save: Callable[[], None],
        notify: Callable[[str, str, str], Any],
        dismiss: Callable[[str], Any],
    ) -> None:
        self.hass = hass
        self.heater_id = heater_id
        self.name = name
        self.config = {**DEFAULTS, **config}
        self.state = state
        base = empty_state()
        for key, value in base.items():
            self.state.setdefault(key, value)
        for key, value in base["relay"].items():
            self.state["relay"].setdefault(key, value)
        self._save = save
        self._notify = notify
        self._dismiss = dismiss
        self._listeners: list[Callable[[], None]] = []
        self._unsubs: list[Callable[[], None]] = []
        self._lock = asyncio.Lock()
        self._pending = False
        # Endast i minnet
        self._startup_check = True
        self._off_since: datetime | None = None
        self._unavailable_since: datetime | None = None
        self._unavailable_warned = False
        self._off_retry_done = False
        # Visningsvärden
        self.need = False
        self.heating_minutes = 0  # publicerad (med hysteres)
        self.exact_minutes = 0  # exakt, från aktuell temperatur
        self.temperature: float | None = None  # beräkningstemperatur (med hysteres)
        self.exact_temperature: float | None = None
        self._calc_set = False
        self._calc_temp: float | None = None
        self._latch: int | None = None  # sista 15 min före start: uppvärmningstid som bara får öka
        self._next_start: datetime | None = None
        self.next_start_preliminary = False
        self._prelim: dict[str, Any] | None = None
        self.temperature_source = "okänd"
        self.status = "Startar"
        self.device_info: Any = None  # sätts av __init__ (reläets enhet eller egen enhet)

    # ---------- egenskaper ----------
    @property
    def relay_entity(self) -> str | None:
        return self.config.get(CONF_RELAY) or None

    @property
    def live(self) -> bool:
        return bool(self.config.get(CONF_LIVE)) and self.relay_entity is not None

    @property
    def relay(self) -> dict[str, Any]:
        return self.state["relay"]

    @property
    def fault(self) -> bool:
        return bool(self.relay["fault"])

    @property
    def max_on(self) -> timedelta:
        return max(
            timedelta(minutes=10),
            timedelta(minutes=self.config[CONF_AUTO_OFF]) - AUTO_OFF_MARGIN,
        )

    # ---------- livscykel ----------
    async def async_start(self) -> None:
        entities = [self.config[CONF_TEMPERATURE]]
        if self.relay_entity:
            entities.append(self.relay_entity)
        self._unsubs.append(
            async_track_state_change_event(self.hass, entities, self._on_state_event)
        )
        self._unsubs.append(
            async_track_time_interval(self.hass, self._on_tick, TICK)
        )
        await self.async_reconcile()

    @callback
    def async_stop(self) -> None:
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()

    @callback
    def subscribe(self, listener: Callable[[], None]) -> Callable[[], None]:
        self._listeners.append(listener)

        def remove() -> None:
            if listener in self._listeners:
                self._listeners.remove(listener)

        return remove

    @callback
    def _on_state_event(self, event: Event) -> None:
        self.hass.async_create_task(self.async_reconcile())

    async def _on_tick(self, _now: datetime) -> None:
        await self.async_reconcile()

    # ---------- temperatur och uppvärmningstid ----------
    def _read_temperature(self, now: datetime) -> float | None:
        state = self.hass.states.get(self.config[CONF_TEMPERATURE])
        try:
            value = float(state.state)  # type: ignore[union-attr]
            if not math.isfinite(value) or not TEMP_VALID[0] <= value <= TEMP_VALID[1]:
                raise ValueError
        except (AttributeError, TypeError, ValueError):
            last = self.state.get("last_temperature")
            last_at = _dt(self.state.get("last_temperature_at"))
            if last is not None and last_at is not None:
                age = now - last_at
                if timedelta(0) <= age <= timedelta(minutes=self.config[CONF_CACHE]):
                    self.temperature_source = "senaste giltiga"
                    return float(last)
            self.temperature_source = "reservtid"
            return None
        self.temperature_source = "givare"
        last = self.state.get("last_temperature")
        if last is None or abs(value - float(last)) >= TEMP_HYSTERESIS or self._stale_saved_temp(now):
            self.state["last_temperature"] = value
            self.state["last_temperature_at"] = now.isoformat()
            self._save()
        return value

    def _stale_saved_temp(self, now: datetime) -> bool:
        last_at = _dt(self.state.get("last_temperature_at"))
        return last_at is None or now - last_at > timedelta(minutes=5)

    def compute_minutes(self, temperature: float | None) -> int:
        cfg = self.config
        if temperature is None:
            minutes = float(cfg[CONF_FALLBACK])
        else:
            minutes = cfg[CONF_BASE] - cfg[CONF_SLOPE] * temperature
        return int(max(cfg[CONF_MIN], min(cfg[CONF_MAX], round(minutes))))

    # ---------- avresor ----------
    def trip_view(self) -> list[dict[str, Any]]:
        now = dt_util.utcnow()
        rows = []
        for trip in self.state["trips"]:
            dep = _dt(trip["departure_at"])
            assert dep is not None
            start = dep - timedelta(minutes=self.heating_minutes)
            skipped = bool(trip.get("skipped"))
            preliminary = not trip.get("started") and start - now > PRELIM_HORIZON
            if preliminary and self._prelim and self._prelim["key"] == (trip["id"], trip["departure_at"]):
                start = self._prelim["value"]  # samma värde som sensorn Nästa start
            rows.append(
                {
                    "id": trip["id"],
                    "departure_at": dep.isoformat(),
                    "label": trip.get("label", ""),
                    "source": "calendar" if trip.get("source") else "manual",
                    "calendar": trip.get("calendar", ""),
                    "skipped": skipped,
                    "started": bool(trip.get("started")),
                    "start_at": start.isoformat(),
                    "preliminary": preliminary,
                    "end_at": (dep + self.after_departure).isoformat(),
                    "active": bool(trip.get("started")) and not skipped and now < dep + self.after_departure,
                }
            )
        return sorted(rows, key=lambda r: r["departure_at"])

    def active_trip_count(self) -> int:
        return sum(1 for t in self.state["trips"] if not t.get("skipped"))

    @property
    def after_departure(self) -> timedelta:
        """Hur länge behovet (och avresan) finns kvar efter avresetiden."""
        return timedelta(minutes=self.config[CONF_AFTER])

    def next_start(self) -> datetime | None:
        """Publicerad nästa start (räknas fram i _update_need)."""
        return self._next_start

    def _pending_trips(self) -> list[tuple[datetime, dict[str, Any]]]:
        out = []
        for trip in self.state["trips"]:
            dep = _dt(trip["departure_at"])
            if dep is not None and not trip.get("started") and not trip.get("skipped"):
                out.append((dep, trip))
        return out

    def _update_minutes(self, now: datetime) -> int:
        """Uppvärmningstid med hysteres på temperaturen.

        Beräkningstemperaturen följer givaren först när den avvikit minst
        TEMP_HYSTERESIS. Inom EXACT_WINDOW före en start får uppvärmningstiden bara
        öka (starttiden kan flyttas tidigare men aldrig senare), så att pendling kring
        en minutgräns inte ger växlande värden.
        Returnerar minuterna som används för startbeslut: max(exakt, publicerad),
        så att uttaget aldrig startar senare än exakt beräknat.
        """
        exact_temp = self._read_temperature(now)
        exact = self.compute_minutes(exact_temp)
        self.exact_temperature = exact_temp
        self.exact_minutes = exact
        published = self.compute_minutes(self._calc_temp) if self._calc_set else exact
        if self._latch is not None:
            published = max(published, self._latch)
        decision = max(exact, published)
        near_start = any(
            dep - timedelta(minutes=decision) - now <= EXACT_WINDOW
            for dep, _trip in self._pending_trips()
        )
        if near_start:
            if self._latch is None or decision > self._latch:
                if exact > published or not self._calc_set:
                    self._calc_set = True
                    self._calc_temp = exact_temp
                self._latch = decision
            self.temperature = self._calc_temp
            self.heating_minutes = self._latch
            return self._latch
        self._latch = None
        published = self.compute_minutes(self._calc_temp) if self._calc_set else exact
        if (
            not self._calc_set
            or (exact_temp is None) != (self._calc_temp is None)
            or (
                exact_temp is not None
                and self._calc_temp is not None
                and abs(exact_temp - self._calc_temp) >= TEMP_HYSTERESIS
            )
        ):
            self._calc_set = True
            self._calc_temp = exact_temp
            published = exact
        self.temperature = self._calc_temp
        self.heating_minutes = published
        return max(exact, published)

    def _update_next_start(self, now: datetime) -> None:
        """Nästa start. Mer än PRELIM_HORIZON fram är den preliminär och uppdateras sällan."""
        pending = self._pending_trips()
        if not pending:
            self._next_start = None
            self.next_start_preliminary = False
            self._prelim = None
            return
        dep, trip = min(pending, key=lambda p: p[0])
        start = dep - timedelta(minutes=self.heating_minutes)
        if start - now <= PRELIM_HORIZON:
            self._next_start = start
            self.next_start_preliminary = False
            self._prelim = None
            return
        key = (trip["id"], trip["departure_at"])
        p = self._prelim
        temp_jump = p is not None and (
            (p["temp"] is None) != (self._calc_temp is None)
            or (
                p["temp"] is not None
                and self._calc_temp is not None
                and abs(p["temp"] - self._calc_temp) >= PRELIM_TEMP_JUMP
            )
        )
        if p is None or p["key"] != key or now - p["at"] >= PRELIM_REFRESH or temp_jump:
            self._prelim = {"key": key, "at": now, "temp": self._calc_temp, "value": start}
        self._next_start = self._prelim["value"]
        self.next_start_preliminary = True

    async def async_add_departure(self, when: datetime, label: str = "") -> str:
        if when + self.after_departure <= dt_util.utcnow():
            raise HomeAssistantError(
                f"Avresetiden har redan passerat (inklusive {self.config[CONF_AFTER]} min efter avresa)"
            )
        trip_id = uuid.uuid4().hex[:12]
        self.state["trips"].append(
            {"id": trip_id, "departure_at": when.isoformat(), "started": False, "label": label}
        )
        self._save()
        await self.async_reconcile()
        return trip_id

    def _trip(self, trip_id: str) -> dict[str, Any]:
        for trip in self.state["trips"]:
            if trip["id"] == trip_id:
                return trip
        raise HomeAssistantError("Avresan finns inte (den kan redan ha tagits bort)")

    async def async_edit_departure(
        self, trip_id: str, when: datetime | None, label: str | None
    ) -> None:
        trip = self._trip(trip_id)
        if trip.get("source"):
            raise HomeAssistantError(
                "Avresan kommer från kalendern. Ändra händelsen i kalendern eller hoppa över avresan."
            )
        if when is not None:
            now = dt_util.utcnow()
            if when + self.after_departure <= now:
                raise HomeAssistantError("Den nya avresetiden har redan passerat")
            trip["departure_at"] = when.isoformat()
            # Flyttas avresan så långt fram att starttiden ligger i framtiden,
            # planeras den om (startad -> ej startad). Annars fortsätter behovet.
            if trip.get("started") and now < when - timedelta(minutes=self.heating_minutes):
                trip["started"] = False
        if label is not None:
            trip["label"] = label
        self._save()
        await self.async_reconcile()

    async def async_remove_departure(self, trip_id: str) -> None:
        trip = self._trip(trip_id)
        if trip.get("source"):
            # En kalenderavresa skulle bara komma tillbaka vid nästa läsning: hoppa över den i stället.
            await self.async_skip_departure(trip_id, True)
            return
        self.state["trips"] = [t for t in self.state["trips"] if t["id"] != trip_id]
        self._save()
        await self.async_reconcile()

    async def async_skip_departure(self, trip_id: str, skip: bool) -> None:
        """Hoppa över (eller återställ) en avresa utan att ta bort den.

        En överhoppad avresa ger inget värmebehov. Hoppas en pågående avresa över
        upphör behovet, precis som när en manuell avresa tas bort.
        """
        trip = self._trip(trip_id)
        trip["skipped"] = bool(skip)
        self._save()
        await self.async_reconcile()

    async def async_sync_calendar(
        self, source_id: str, calendar_name: str, departures: list[dict[str, Any]]
    ) -> None:
        """Ersätt avresorna från en kalenderkoppling med aktuellt läsresultat.

        departures: [{"id", "departure_at" (datetime, UTC), "label"}]
        - Nya avresor läggs till (om avresa + tiden efter avresa inte har passerat).
        - Avresor som inte längre finns i kalendern tas bort, utom när
          uppvärmningen redan har startat: de ligger kvar till avresa + tiden efter avresa.
        - Överhoppning och startstatus behålls för avresor som finns kvar.
        """
        now = dt_util.utcnow()
        wanted = {d["id"]: d for d in departures if d["departure_at"] + self.after_departure > now}
        changed = False
        kept: list[dict[str, Any]] = []
        for trip in self.state["trips"]:
            if trip.get("source") != source_id:
                kept.append(trip)
                continue
            if trip["id"] in wanted:
                new = wanted.pop(trip["id"])
                if trip.get("label") != new["label"] or trip.get("calendar") != calendar_name:
                    trip["label"] = new["label"]
                    trip["calendar"] = calendar_name
                    changed = True
                kept.append(trip)
            elif trip.get("started") and not trip.get("skipped"):
                kept.append(trip)  # pågående uppvärmning avbryts inte av en ändrad kalender
            else:
                changed = True
        for dep in wanted.values():
            kept.append(
                {
                    "id": dep["id"],
                    "departure_at": dep["departure_at"].isoformat(),
                    "started": False,
                    "label": dep["label"],
                    "source": source_id,
                    "calendar": calendar_name,
                    "skipped": False,
                }
            )
            changed = True
        if changed:
            self.state["trips"] = kept
            self._save()
            await self.async_reconcile()

    async def async_drop_calendar_sources(self, valid: set[str]) -> None:
        """Ta bort ej startade avresor från kalenderkopplingar som inte längre gäller."""
        before = len(self.state["trips"])
        self.state["trips"] = [
            t for t in self.state["trips"]
            if not t.get("source") or t["source"] in valid or (t.get("started") and not t.get("skipped"))
        ]
        if len(self.state["trips"]) != before:
            self._save()

    async def async_force(self, minutes: int) -> None:
        if self.fault:
            raise HomeAssistantError("Säkerhetsspärren är aktiv. Kvittera den först.")
        self.state["force_until"] = (dt_util.utcnow() + timedelta(minutes=minutes)).isoformat()
        # Forcerad start är ett uttryckligt startkommando och häver spärr för behovsperioden.
        self.relay["inhibited"] = False
        self.relay["inhibit_reason"] = None
        self._save()
        await self.async_reconcile()

    async def async_stop_force(self) -> None:
        self.state["force_until"] = None
        self._save()
        await self.async_reconcile()

    async def async_stop_heating(self) -> None:
        """Avsluta pågående värmning nu.

        Pågående kalenderavresor hoppas över (kan återställas), pågående manuella
        avresor tas bort och en forcering avbryts. Avresor som ännu inte startat
        påverkas inte. Reläet slås av som ett vanligt, beordrat frånslag (ingen spärr).
        """
        kept = []
        for trip in self.state["trips"]:
            if trip.get("started") and not trip.get("skipped"):
                if trip.get("source"):  # kalenderavresa (source = kalenderkopplingens id)
                    trip["skipped"] = True
                else:
                    continue  # manuell pågående avresa tas bort
            kept.append(trip)
        self.state["trips"] = kept
        self.state["force_until"] = None
        self._save()
        await self.async_reconcile()

    async def async_acknowledge(self) -> None:
        relay = self.relay
        was_fault = relay["fault"]
        relay["fault"] = False
        relay["fault_reason"] = None
        relay["fault_at"] = None
        if was_fault and self.need:
            relay["inhibited"] = True
            relay["inhibit_reason"] = "Kvitterad spärr – startar vid nästa behov eller forcerad start"
        self._save()
        self._dismiss(f"motorvarmare_{self.heater_id}")
        await self.async_reconcile()

    # ---------- avstämning ----------
    async def async_reconcile(self) -> None:
        if self._lock.locked():
            self._pending = True
            return
        async with self._lock:
            while True:
                self._pending = False
                try:
                    await self._reconcile_once()
                except Exception:  # noqa: BLE001
                    _LOGGER.exception("%s: fel vid avstämning", self.name)
                if not self._pending:
                    break
        for listener in list(self._listeners):
            listener()

    def _update_need(self, now: datetime) -> None:
        start_minutes = self._update_minutes(now)
        remaining = []
        changed = False
        active = False
        for trip in self.state["trips"]:
            dep = _dt(trip["departure_at"])
            if dep is None or now >= dep + self.after_departure:
                changed = True
                continue
            if trip.get("skipped"):
                remaining.append(trip)
                continue
            if not trip.get("started") and now >= dep - timedelta(minutes=start_minutes):
                trip["started"] = True  # låses: temperaturökning avbryter inte
                changed = True
            active = active or bool(trip.get("started"))
            remaining.append(trip)
        self.state["trips"] = remaining
        force_until = _dt(self.state.get("force_until"))
        if force_until is not None and now >= force_until:
            self.state["force_until"] = None
            force_until = None
            changed = True
        self._update_next_start(now)
        self.need = active or force_until is not None
        if not self.need and self.relay["inhibited"]:
            self.relay["inhibited"] = False  # behovsperioden är slut
            self.relay["inhibit_reason"] = None
            changed = True
        if changed:
            self._save()

    async def _reconcile_once(self) -> None:
        now = dt_util.utcnow()
        self._update_need(now)
        relay = self.relay

        if not self.relay_entity:
            self.status = "Testläge (inget relä valt)"
            return
        if not self.live:
            if relay["commanded"] == "on":
                # Lämnar live-läge: slå av det integrationen själv slagit på, sedan inga fler kommandon.
                await self._command("off", now)
            self.status = "Testläge – reläet styrs inte"
            return

        rstate = self.hass.states.get(self.relay_entity)
        observed = rstate.state if rstate else "unavailable"

        # S6: otillgängligt relä
        if observed not in ("on", "off"):
            self._off_since = None
            if self._unavailable_since is None:
                self._unavailable_since = now
            if (
                self.need
                and not self._unavailable_warned
                and now - self._unavailable_since >= UNAVAILABLE_WARN
            ):
                self._unavailable_warned = True
                self._notify(
                    f"motorvarmare_{self.heater_id}_otillganglig",
                    f"{self.name}: reläet svarar inte",
                    "Reläet har varit otillgängligt i minst 2 minuter under värmebehov. "
                    "Inga kommandon skickas förrän det svarar igen.",
                )
            self.status = "Relä otillgängligt"
            return
        if self._unavailable_warned:
            self._dismiss(f"motorvarmare_{self.heater_id}_otillganglig")
        self._unavailable_since = None
        self._unavailable_warned = False

        # S3: första observation efter start/omladdning
        if self._startup_check:
            self._startup_check = False
            if relay["commanded"] == "on" and observed == "off" and not relay["fault"]:
                on_at = _dt(relay["on_at"]) or _dt(relay["commanded_at"]) or now
                relay["commanded"] = "off"
                relay["commanded_at"] = now.isoformat()
                if now - on_at >= self.max_on:
                    relay["inhibited"] = self.need
                    relay["inhibit_reason"] = "Maxtid passerad under avbrott" if self.need else None
                else:
                    self._set_fault(
                        now, "Reläet var avslaget efter omstart av Home Assistant, trots att det skulle vara på"
                    )
                self._save()

        # S1: spärr
        if relay["fault"]:
            if observed == "on" and relay["commanded"] != "off":
                await self._command("off", now)
            self.status = "Säkerhetsspärr"
            return

        if relay["commanded"] == "on":
            await self._handle_commanded_on(now, observed)
        else:
            await self._handle_commanded_off(now, observed)

        if relay["fault"]:
            self.status = "Säkerhetsspärr"
        elif relay["commanded"] == "on":
            self.status = "Värmer" if relay["confirmed"] else "Väntar på att reläet slår till"
        elif self.need and relay["inhibited"]:
            self.status = relay["inhibit_reason"] or "Spärrad för denna behovsperiod"
        else:
            self.status = "Viloläge"

    async def _handle_commanded_on(self, now: datetime, observed: str) -> None:
        relay = self.relay
        on_at = _dt(relay["on_at"]) or now
        if observed == "on":
            self._off_since = None
            if not relay["confirmed"]:
                relay["confirmed"] = True
                self._save()
            if now - on_at >= self.max_on:
                relay["inhibited"] = self.need
                relay["inhibit_reason"] = "Maxtid nådd (före Shellyns Auto Off)" if self.need else None
                await self._command("off", now)
            elif not self.need:
                await self._command("off", now)
            return
        # observed == "off"
        if not self.need:
            relay["commanded"] = "off"
            relay["commanded_at"] = now.isoformat()
            self._off_since = None
            self._save()
            return
        if not relay["confirmed"]:
            commanded_at = _dt(relay["commanded_at"]) or now
            if now - commanded_at >= RELAY_CONFIRM:
                self._set_fault(now, "Reläet slog inte till inom 30 sekunder")
                await self._command("off", now)
            return
        if self._off_since is None:
            self._off_since = now
            return
        if now - self._off_since >= RELAY_CONFIRM:
            self._set_fault(now, "Reläet slog ifrån oväntat (t.ex. Auto Off, strömavbrott eller manuellt)")
            await self._command("off", now)

    async def _handle_commanded_off(self, now: datetime, observed: str) -> None:
        relay = self.relay
        self._off_since = None
        if self.need and not relay["inhibited"]:
            if observed == "on":
                # Reläet är redan på utan integrationens kommando: ta över utan att
                # förlänga – maxtiden räknas från när reläet slog till.
                rstate = self.hass.states.get(self.relay_entity)  # type: ignore[arg-type]
                started = rstate.last_changed if rstate else now
                relay.update(
                    commanded="on",
                    commanded_at=now.isoformat(),
                    on_at=dt_util.as_utc(started).isoformat(),
                    confirmed=True,
                )
                self._save()
                return
            await self._command("on", now)
            return
        if observed == "on" and relay["commanded"] == "off":
            commanded_at = _dt(relay["commanded_at"])
            if (
                commanded_at is not None
                and now - commanded_at >= RELAY_CONFIRM
                and not self._off_retry_done
                and now - commanded_at < RELAY_CONFIRM * 4
            ):
                self._off_retry_done = True
                await self._command("off", now, retry=True)
                self._notify(
                    f"motorvarmare_{self.heater_id}_avslag",
                    f"{self.name}: reläet slog inte ifrån",
                    "Reläet är fortfarande på efter avslagskommando. Ett nytt försök har gjorts; kontrollera uttaget.",
                )

    def _set_fault(self, now: datetime, reason: str) -> None:
        relay = self.relay
        relay["fault"] = True
        relay["fault_reason"] = reason
        relay["fault_at"] = now.isoformat()
        self._save()
        _LOGGER.warning("%s: säkerhetsspärr – %s", self.name, reason)
        self._notify(
            f"motorvarmare_{self.heater_id}",
            f"{self.name}: säkerhetsspärr",
            f"{reason}. Uttaget slås inte på igen automatiskt. Kontrollera bilen och kvittera spärren.",
        )

    async def _command(self, action: str, now: datetime, retry: bool = False) -> None:
        relay = self.relay
        assert self.relay_entity
        # Avsikten sparas före kommandot (omstart mitt i ett kommando ska tolkas säkert).
        relay["commanded"] = action
        relay["commanded_at"] = now.isoformat()
        if action == "on":
            relay["on_at"] = now.isoformat()
            relay["confirmed"] = False
        elif not retry:
            self._off_retry_done = False
        self._save()
        try:
            await self.hass.services.async_call(
                "switch", f"turn_{action}", {"entity_id": self.relay_entity}, blocking=True
            )
        except Exception as err:  # noqa: BLE001
            _LOGGER.error("%s: kommando %s misslyckades: %s", self.name, action, err)
            if action == "on" and not relay["fault"]:
                self._set_fault(now, f"PÅ-kommandot till reläet misslyckades ({err})")

    # ---------- visning ----------
    def attributes(self) -> dict[str, Any]:
        relay = self.relay
        return {
            "heater_id": self.heater_id,
            "test_mode": not self.live,
            "status": self.status,
            "need": self.need,
            "fault": relay["fault"],
            "fault_reason": relay["fault_reason"],
            "fault_at": relay["fault_at"],
            "inhibited": relay["inhibited"],
            "inhibit_reason": relay["inhibit_reason"],
            "heating_minutes": self.heating_minutes,
            "temperature": self.temperature,
            "temperature_source": self.temperature_source,
            "next_start": _iso(self.next_start()),
            "next_start_preliminary": self.next_start_preliminary,
            "force_until": self.state.get("force_until"),
            "trips": self.trip_view(),
            "relay_entity": self.relay_entity,
        }
