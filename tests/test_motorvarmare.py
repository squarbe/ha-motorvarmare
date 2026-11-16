"""Tester för Motorvärmare 0.2 (testmatrisen i överlämningen + säkerhetsinvarianterna S1–S6)."""
from datetime import timedelta

import pytest

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import HomeAssistantError
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
    async_mock_service,
)

DOMAIN = "motorvarmare"
TEMP = "sensor.ute"
RELAY = "switch.mv1"
RELAY2 = "switch.mv2"
SID = "mv1sub"
SID2 = "mv2sub"


def sub(sid, title, relay, live=True, **extra):
    data = {"temperature_entity": TEMP, "live_control": live, "auto_off_minutes": 240,
            "base_minutes": 60, "minutes_per_degree": 3.0, "minimum_minutes": 0,
            "maximum_minutes": 240, "fallback_minutes": 180, "temperature_cache_minutes": 30, **extra}
    if relay:
        data["relay_entity"] = relay
    return {"data": data, "subentry_id": sid, "subentry_type": "uttag", "title": title, "unique_id": None}


class Env:
    def __init__(self, hass, entry, on, off, notes):
        self.hass, self.entry, self.on, self.off, self.notes = hass, entry, on, off, notes

    def s(self, eid):
        return self.hass.states.get(eid)

    async def call(self, service, sid=SID, **data):
        return await self.hass.services.async_call(DOMAIN, service, {"heater_id": sid, **data}, blocking=True,
                                                   return_response=service == "add_departure")

    async def tick(self, freezer, delta):
        freezer.tick(delta)
        async_fire_time_changed(self.hass)
        await self.hass.async_block_till_done()

    async def relay(self, state, eid=RELAY):
        self.hass.states.async_set(eid, state)
        await self.hass.async_block_till_done()


@pytest.fixture
def make(hass: HomeAssistant, hass_storage):
    async def _make(subs=None, relay="off", temp="0", stored=None, notify=True, options=None):
        hass.states.async_set(TEMP, temp)
        hass.states.async_set(RELAY, relay)
        hass.states.async_set(RELAY2, "off")
        if stored is not None:
            hass_storage["motorvarmare.state"] = {"version": 1, "minor_version": 1, "key": "motorvarmare.state",
                                                  "data": {"heaters": stored}}
        on = async_mock_service(hass, "switch", "turn_on")
        off = async_mock_service(hass, "switch", "turn_off")
        notes = async_mock_service(hass, "notify", "mobile_app_ia") if notify else []
        entry = MockConfigEntry(domain=DOMAIN, title="Motorvärmare", data={}, version=2,
                                options=options if options is not None else {"notify_service": "mobile_app_ia"},
                                subentries_data=subs if subs is not None else [sub(SID, "Motorvärmare 1", RELAY)])
        entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        return Env(hass, entry, on, off, notes)
    return _make


def relay_state(**kw):
    base = {"commanded": None, "commanded_at": None, "on_at": None, "confirmed": False, "fault": False,
            "fault_reason": None, "fault_at": None, "inhibited": False, "inhibit_reason": None}
    base.update(kw)
    return base


def active_trip(minutes_to_departure=30):
    dep = dt_util.utcnow() + timedelta(minutes=minutes_to_departure)
    return {"id": "t1", "departure_at": dep.isoformat(), "started": True, "label": ""}


# ---------------- konfiguration ----------------

async def test_config_flow_and_single_instance(hass):
    r = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    r = await hass.config_entries.flow.async_configure(r["flow_id"], {})
    assert r["type"] is FlowResultType.CREATE_ENTRY
    r = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert r["type"] is FlowResultType.ABORT and r["reason"] == "single_instance_allowed"


async def test_add_heater_via_subentry_and_validation(hass, make):
    env = await make(subs=[])
    entry = env.entry
    r = await hass.config_entries.subentries.async_init((entry.entry_id, "uttag"), context={"source": "user"})
    assert r["type"] is FlowResultType.FORM
    base = {"name": "Motorvärmare 1", "temperature_entity": TEMP, "relay_entity": RELAY, "live_control": False,
            "auto_off_minutes": 240, "base_minutes": 60, "minutes_per_degree": 3, "minimum_minutes": 200,
            "maximum_minutes": 100, "fallback_minutes": 180, "temperature_cache_minutes": 30}
    r = await hass.config_entries.subentries.async_configure(r["flow_id"], base)
    assert r["errors"] == {"minimum_minutes": "min_over_max"}
    r = await hass.config_entries.subentries.async_configure(r["flow_id"], {**{k: v for k, v in base.items() if k != "relay_entity"}, "minimum_minutes": 0, "live_control": True})
    assert r["errors"] == {"live_control": "live_needs_relay"}
    r = await hass.config_entries.subentries.async_configure(r["flow_id"], {**base, "minimum_minutes": 0})
    assert r["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert hass.states.get("sensor.motorvarmare_1_status") is not None
    assert hass.states.get("binary_sensor.motorvarmare_1_varmebehov").state == "off"
    # Samma relä på uttag 2 nekas
    r = await hass.config_entries.subentries.async_init((entry.entry_id, "uttag"), context={"source": "user"})
    r = await hass.config_entries.subentries.async_configure(r["flow_id"], {**base, "name": "Motorvärmare 2", "minimum_minutes": 0})
    assert r["errors"] == {"relay_entity": "relay_in_use"}


async def test_entity_ids_and_no_statistics(hass, make):
    await make()
    for eid in ["sensor.motorvarmare_1_status", "sensor.motorvarmare_1_uppvarmningstid", "sensor.motorvarmare_1_avresor",
                "sensor.motorvarmare_1_nasta_start", "binary_sensor.motorvarmare_1_varmebehov",
                "binary_sensor.motorvarmare_1_sakerhetssparr", "button.motorvarmare_1_kvittera_sparr",
                "button.motorvarmare_1_stoppa_forcering"]:
        st = hass.states.get(eid)
        assert st is not None, eid
        assert "state_class" not in st.attributes, eid


async def test_two_heaters_independent(hass, make, freezer):
    env = await make(subs=[sub(SID, "Motorvärmare 1", RELAY), sub(SID2, "Motorvärmare 2", RELAY2)])
    await env.call("force_start", SID, minutes=30)
    assert [c.data["entity_id"] for c in env.on] == [RELAY]
    assert env.s("binary_sensor.motorvarmare_2_varmebehov").state == "off"


# ---------------- avresor och behov ----------------

async def test_testmode_never_commands(hass, make, freezer):
    env = await make(subs=[sub(SID, "Motorvärmare 1", RELAY, live=False)])
    await env.call("add_departure", departure_at=(dt_util.now() + timedelta(minutes=30)).isoformat())
    assert env.s("binary_sensor.motorvarmare_1_varmebehov").state == "on"
    assert not env.on and not env.off
    assert env.s("sensor.motorvarmare_1_avresor").attributes["test_mode"] is True


async def test_need_window_and_end_at_departure_plus_60(hass, make, freezer):
    env = await make()
    dep = dt_util.now() + timedelta(minutes=90)  # 0 °C -> 60 min
    resp = await env.call("add_departure", departure_at=dep.isoformat())
    assert "trip_id" in resp
    assert env.s("binary_sensor.motorvarmare_1_varmebehov").state == "off"
    await env.tick(freezer, timedelta(minutes=29))
    assert env.s("binary_sensor.motorvarmare_1_varmebehov").state == "off"
    await env.tick(freezer, timedelta(minutes=1, seconds=15))
    assert env.s("binary_sensor.motorvarmare_1_varmebehov").state == "on"
    assert len(env.on) == 1
    await env.relay("on")
    await env.tick(freezer, timedelta(minutes=60 + 59))
    assert env.s("binary_sensor.motorvarmare_1_varmebehov").state == "on"
    await env.tick(freezer, timedelta(minutes=1, seconds=15))
    assert env.s("binary_sensor.motorvarmare_1_varmebehov").state == "off"
    assert len(env.off) == 1
    assert env.s("sensor.motorvarmare_1_avresor").state == "0"


async def test_naive_local_time_is_local(hass, make):
    env = await make(subs=[sub(SID, "Motorvärmare 1", RELAY, live=False)])
    local = (dt_util.now() + timedelta(hours=5)).replace(second=0, microsecond=0)
    await env.call("add_departure", departure_at=local.strftime("%Y-%m-%d %H:%M:%S"))
    trip = env.s("sensor.motorvarmare_1_avresor").attributes["trips"][0]
    assert dt_util.parse_datetime(trip["departure_at"]) == local


async def test_late_registration_starts_immediately(hass, make):
    env = await make(temp="-20")  # 120 min
    await env.call("add_departure", departure_at=(dt_util.now() + timedelta(minutes=20)).isoformat())
    assert env.s("binary_sensor.motorvarmare_1_varmebehov").state == "on"
    assert len(env.on) == 1


async def test_past_departure_rejected(hass, make):
    env = await make()
    with pytest.raises(HomeAssistantError):
        await env.call("add_departure", departure_at=(dt_util.now() - timedelta(minutes=61)).isoformat())


async def test_overlapping_departures(hass, make, freezer):
    env = await make(subs=[sub(SID, "Motorvärmare 1", RELAY, live=False)])
    now = dt_util.now()
    await env.call("add_departure", departure_at=(now + timedelta(minutes=10)).isoformat())
    await env.call("add_departure", departure_at=(now + timedelta(minutes=80)).isoformat())
    await env.tick(freezer, timedelta(minutes=71))  # första: 10+60 passerad
    attrs = env.s("sensor.motorvarmare_1_avresor").attributes
    assert len(attrs["trips"]) == 1 and attrs["trips"][0]["started"]
    assert env.s("binary_sensor.motorvarmare_1_varmebehov").state == "on"


async def test_temperature_rise_does_not_cancel_started(hass, make, freezer):
    env = await make(subs=[sub(SID, "Motorvärmare 1", RELAY, live=False)], temp="-20")
    await env.call("add_departure", departure_at=(dt_util.now() + timedelta(minutes=100)).isoformat())
    assert env.s("binary_sensor.motorvarmare_1_varmebehov").state == "on"
    hass.states.async_set(TEMP, "10")
    await hass.async_block_till_done()
    assert env.s("binary_sensor.motorvarmare_1_varmebehov").state == "on"
    assert env.s("sensor.motorvarmare_1_uppvarmningstid").state == "30"


async def test_temperature_before_start_moves_start(hass, make):
    env = await make(subs=[sub(SID, "Motorvärmare 1", RELAY, live=False)], temp="10")
    await env.call("add_departure", departure_at=(dt_util.now() + timedelta(minutes=100)).isoformat())
    assert env.s("binary_sensor.motorvarmare_1_varmebehov").state == "off"
    hass.states.async_set(TEMP, "-20")  # 120 min > 100 -> starta nu
    await hass.async_block_till_done()
    assert env.s("binary_sensor.motorvarmare_1_varmebehov").state == "on"


async def test_temperature_cache_then_fallback(hass, make, freezer):
    env = await make(subs=[sub(SID, "Motorvärmare 1", RELAY, live=False)], temp="-10")
    assert env.s("sensor.motorvarmare_1_uppvarmningstid").state == "90"
    hass.states.async_set(TEMP, "unavailable")
    await hass.async_block_till_done()
    assert env.s("sensor.motorvarmare_1_uppvarmningstid").state == "90"
    await env.tick(freezer, timedelta(minutes=31))
    assert env.s("sensor.motorvarmare_1_uppvarmningstid").state == "180"
    for bad in ("nan", "inf", "-99", "abc"):
        hass.states.async_set(TEMP, bad)
        await hass.async_block_till_done()
        assert env.s("sensor.motorvarmare_1_uppvarmningstid").state == "180"


async def test_temperature_persisted(hass, make, hass_storage, freezer):
    env = await make(temp="-7")
    await env.tick(freezer, timedelta(seconds=20))
    saved = hass_storage["motorvarmare.state"]["data"]["heaters"][SID]
    assert saved["last_temperature"] == -7.0


async def test_edit_started_trip_far_ahead_replans(hass, make, freezer):
    env = await make()
    await env.call("add_departure", departure_at=(dt_util.now() + timedelta(minutes=30)).isoformat())
    await env.relay("on")
    trip = env.s("sensor.motorvarmare_1_avresor").attributes["trips"][0]
    await env.call("edit_departure", trip_id=trip["id"], departure_at=(dt_util.now() + timedelta(hours=5)).isoformat())
    assert env.s("binary_sensor.motorvarmare_1_varmebehov").state == "off"
    assert len(env.off) == 1


async def test_edit_started_trip_slightly_keeps_need(hass, make):
    env = await make()
    await env.call("add_departure", departure_at=(dt_util.now() + timedelta(minutes=30)).isoformat())
    trip = env.s("sensor.motorvarmare_1_avresor").attributes["trips"][0]
    await env.call("edit_departure", trip_id=trip["id"], departure_at=(dt_util.now() + timedelta(minutes=50)).isoformat())
    assert env.s("binary_sensor.motorvarmare_1_varmebehov").state == "on"


async def test_remove_active_trip_with_force_parallel(hass, make):
    env = await make()
    await env.call("add_departure", departure_at=(dt_util.now() + timedelta(minutes=30)).isoformat())
    await env.relay("on")
    await env.call("force_start", minutes=60)
    trip = env.s("sensor.motorvarmare_1_avresor").attributes["trips"][0]
    await env.call("remove_departure", trip_id=trip["id"])
    assert env.s("binary_sensor.motorvarmare_1_varmebehov").state == "on"
    await env.call("stop_force")
    assert env.s("binary_sensor.motorvarmare_1_varmebehov").state == "off"
    assert len(env.off) == 1


# ---------------- relä och säkerhet ----------------

async def test_s2_unexpected_off_30s_gives_fault_and_alarm_once(hass, make, freezer):
    env = await make()
    await env.call("force_start", minutes=120)
    await env.relay("on")
    await env.tick(freezer, timedelta(minutes=10))
    await env.relay("off")
    assert env.s("binary_sensor.motorvarmare_1_sakerhetssparr").state == "off"
    await env.tick(freezer, timedelta(seconds=15))
    await env.tick(freezer, timedelta(seconds=16))
    assert env.s("binary_sensor.motorvarmare_1_sakerhetssparr").state == "on"
    assert len(env.notes) == 1
    assert len(env.on) == 1  # aldrig återinkopplat
    await env.tick(freezer, timedelta(minutes=10))
    assert len(env.on) == 1 and len(env.notes) == 1


async def test_short_glitch_no_fault(hass, make, freezer):
    env = await make()
    await env.call("force_start", minutes=120)
    await env.relay("on")
    await env.tick(freezer, timedelta(minutes=10))
    await env.relay("off")
    await env.tick(freezer, timedelta(seconds=15))
    await env.relay("on")
    await env.tick(freezer, timedelta(seconds=30))
    assert env.s("binary_sensor.motorvarmare_1_sakerhetssparr").state == "off"
    assert len(env.on) == 1


async def test_relay_does_not_confirm(hass, make, freezer):
    env = await make()
    await env.call("force_start", minutes=60)
    await env.tick(freezer, timedelta(seconds=31))
    assert env.s("binary_sensor.motorvarmare_1_sakerhetssparr").state == "on"
    assert "slog inte till" in env.s("binary_sensor.motorvarmare_1_sakerhetssparr").attributes["orsak"]


async def test_s6_unavailable_is_not_off(hass, make, freezer):
    env = await make()
    await env.call("force_start", minutes=60)
    await env.relay("on")
    await env.relay("unavailable")
    await env.tick(freezer, timedelta(minutes=1))
    assert env.s("binary_sensor.motorvarmare_1_sakerhetssparr").state == "off"
    assert len(env.notes) == 0
    await env.tick(freezer, timedelta(minutes=1, seconds=15))
    assert len(env.notes) == 1  # varning, ingen spärr
    assert env.s("sensor.motorvarmare_1_status").state == "Relä otillgängligt"
    await env.relay("on")
    await env.tick(freezer, timedelta(seconds=15))
    assert env.s("binary_sensor.motorvarmare_1_sakerhetssparr").state == "off"
    assert len(env.on) == 1


async def test_s3_restart_relay_off_after_on_gives_fault(hass, make):
    now = dt_util.utcnow()
    stored = {SID: {"trips": [active_trip()], "force_until": None, "last_temperature": 0,
                    "last_temperature_at": now.isoformat(),
                    "relay": relay_state(commanded="on", commanded_at=(now - timedelta(hours=1)).isoformat(),
                                         on_at=(now - timedelta(hours=1)).isoformat(), confirmed=True)}}
    env = await make(relay="off", stored=stored)
    assert env.s("binary_sensor.motorvarmare_1_sakerhetssparr").state == "on"
    assert not env.on
    assert len(env.notes) == 1


async def test_s3_restart_after_max_time_inhibits_without_alarm(hass, make):
    now = dt_util.utcnow()
    stored = {SID: {"trips": [active_trip()], "force_until": None, "last_temperature": 0,
                    "last_temperature_at": now.isoformat(),
                    "relay": relay_state(commanded="on", commanded_at=(now - timedelta(hours=4)).isoformat(),
                                         on_at=(now - timedelta(hours=4)).isoformat(), confirmed=True)}}
    env = await make(relay="off", stored=stored)
    assert env.s("binary_sensor.motorvarmare_1_sakerhetssparr").state == "off"
    assert not env.on and not env.notes
    assert "Maxtid" in env.s("sensor.motorvarmare_1_status").state


async def test_s3_restart_relay_still_on_continues(hass, make):
    now = dt_util.utcnow()
    stored = {SID: {"trips": [active_trip()], "force_until": None, "last_temperature": 0,
                    "last_temperature_at": now.isoformat(),
                    "relay": relay_state(commanded="on", commanded_at=(now - timedelta(minutes=40)).isoformat(),
                                         on_at=(now - timedelta(minutes=40)).isoformat(), confirmed=True)}}
    env = await make(relay="on", stored=stored)
    assert env.s("sensor.motorvarmare_1_status").state == "Värmer"
    assert not env.on and not env.off


async def test_s3_restart_before_any_command_resumes(hass, make):
    """Användarens val: återuppta automatiskt när det inte finns ett utestående PÅ-kommando."""
    now = dt_util.utcnow()
    stored = {SID: {"trips": [active_trip()], "force_until": None, "last_temperature": 0,
                    "last_temperature_at": now.isoformat(), "relay": relay_state(commanded="off",
                                                                                commanded_at=now.isoformat())}}
    env = await make(relay="off", stored=stored)
    assert len(env.on) == 1


async def test_s3_relay_unavailable_at_restart_defers_check(hass, make, freezer):
    now = dt_util.utcnow()
    stored = {SID: {"trips": [active_trip(90)], "force_until": None, "last_temperature": 0,
                    "last_temperature_at": now.isoformat(),
                    "relay": relay_state(commanded="on", commanded_at=(now - timedelta(hours=1)).isoformat(),
                                         on_at=(now - timedelta(hours=1)).isoformat(), confirmed=True)}}
    env = await make(relay="unavailable", stored=stored)
    assert env.s("binary_sensor.motorvarmare_1_sakerhetssparr").state == "off"
    await env.relay("off")
    assert env.s("binary_sensor.motorvarmare_1_sakerhetssparr").state == "on"
    assert not env.on


async def test_s4_max_on_time_switches_off_before_auto_off(hass, make, freezer):
    env = await make()
    await env.call("add_departure", departure_at=(dt_util.now() + timedelta(minutes=10)).isoformat())
    await env.call("force_start", minutes=240)
    await env.relay("on")
    await env.tick(freezer, timedelta(minutes=234))
    assert not env.off
    await env.tick(freezer, timedelta(minutes=1, seconds=15))
    assert len(env.off) == 1
    await env.relay("off")
    await env.tick(freezer, timedelta(minutes=2))
    assert len(env.on) == 1  # ingen återinkoppling inom samma behovsperiod
    assert env.s("binary_sensor.motorvarmare_1_sakerhetssparr").state == "off"


async def test_s5_acknowledge_does_not_start(hass, make, freezer):
    env = await make()
    await env.call("force_start", minutes=120)
    await env.tick(freezer, timedelta(seconds=31))  # slog aldrig till -> spärr
    assert env.s("binary_sensor.motorvarmare_1_sakerhetssparr").state == "on"
    with pytest.raises(HomeAssistantError):
        await env.call("force_start", minutes=60)
    await hass.services.async_call("button", "press", {"entity_id": "button.motorvarmare_1_kvittera_sparr"}, blocking=True)
    await hass.async_block_till_done()
    assert env.s("binary_sensor.motorvarmare_1_sakerhetssparr").state == "off"
    await env.tick(freezer, timedelta(minutes=1))
    assert len(env.on) == 1
    await env.call("force_start", minutes=30)  # uttryckligt start
    assert len(env.on) == 2


async def test_s5_new_need_period_after_ack_starts(hass, make, freezer):
    env = await make()
    await env.call("force_start", minutes=15)
    await env.tick(freezer, timedelta(seconds=31))
    await env.call("acknowledge_fault")
    await env.tick(freezer, timedelta(minutes=15))  # behovsperioden slut
    await env.call("add_departure", departure_at=(dt_util.now() + timedelta(minutes=30)).isoformat())
    assert len(env.on) == 2


async def test_s1_fault_survives_restart(hass, make):
    now = dt_util.utcnow()
    stored = {SID: {"trips": [active_trip()], "force_until": None, "last_temperature": 0,
                    "last_temperature_at": now.isoformat(),
                    "relay": relay_state(commanded="off", fault=True, fault_reason="test", fault_at=now.isoformat())}}
    env = await make(relay="off", stored=stored)
    assert env.s("binary_sensor.motorvarmare_1_sakerhetssparr").state == "on"
    assert not env.on


async def test_external_on_during_fault_not_fought_but_never_commanded_on(hass, make, freezer):
    env = await make()
    await env.call("force_start", minutes=60)
    await env.tick(freezer, timedelta(seconds=31))
    offs = len(env.off)
    await env.relay("on")
    await env.tick(freezer, timedelta(minutes=1))
    assert len(env.on) == 1 and len(env.off) == offs


async def test_on_command_failure_gives_fault(hass, make):
    env = await make()

    async def boom(call):
        raise HomeAssistantError("timeout")

    hass.services.async_register("switch", "turn_on", boom)
    await env.call("force_start", minutes=60)
    assert env.s("binary_sensor.motorvarmare_1_sakerhetssparr").state == "on"


async def test_leaving_live_mode_switches_off_own_relay(hass, make):
    env = await make()
    await env.call("force_start", minutes=60)
    await env.relay("on")
    sub_obj = env.entry.subentries[SID]
    hass.config_entries.async_update_subentry(env.entry, sub_obj, data={**sub_obj.data, "live_control": False})
    await hass.async_block_till_done()
    assert len(env.off) == 1
    assert env.s("sensor.motorvarmare_1_status").state.startswith("Testläge")


async def test_reload_unload_and_services_survive(hass, make):
    env = await make()
    await env.call("add_departure", departure_at=(dt_util.now() + timedelta(hours=3)).isoformat())
    assert await hass.config_entries.async_reload(env.entry.entry_id)
    await hass.async_block_till_done()
    assert env.s("sensor.motorvarmare_1_avresor").state == "1"
    assert await hass.config_entries.async_unload(env.entry.entry_id)
    with pytest.raises(HomeAssistantError):
        await env.call("stop_force")
    assert await hass.config_entries.async_setup(env.entry.entry_id)
    await hass.async_block_till_done()
    await env.call("stop_force")


async def test_remove_subentry_cleans_state(hass, make, hass_storage):
    env = await make(subs=[sub(SID, "Motorvärmare 1", RELAY), sub(SID2, "Motorvärmare 2", RELAY2)])
    hass.config_entries.async_remove_subentry(env.entry, SID2)
    await hass.async_block_till_done()
    assert hass.states.get("sensor.motorvarmare_2_status") is None
    assert await hass.config_entries.async_unload(env.entry.entry_id)
    assert SID2 not in hass_storage["motorvarmare.state"]["data"]["heaters"]


async def test_notify_missing_still_persistent(hass, make, freezer):
    from homeassistant.components import persistent_notification as pn
    env = await make(notify=False)
    await env.call("force_start", minutes=60)
    await env.tick(freezer, timedelta(seconds=31))
    assert env.s("binary_sensor.motorvarmare_1_sakerhetssparr").state == "on"
    notes = pn._async_get_or_create_notifications(hass)
    assert any(n.startswith("motorvarmare_") for n in notes)
    await env.call("acknowledge_fault")
    notes = pn._async_get_or_create_notifications(hass)
    assert not any(n == f"motorvarmare_{SID}" for n in notes)


async def test_alarm_payload(hass, make, freezer):
    env = await make()
    await env.call("force_start", minutes=60)
    await env.tick(freezer, timedelta(seconds=31))
    data = env.notes[0].data
    assert "säkerhetsspärr" in data["title"] and data["data"]["tag"] == f"motorvarmare_{SID}"


async def test_dst_spring_forward_uses_real_duration(hass, make, freezer):
    """Avresa 03:30 lokal tid natten då klockan ställs fram: start = 120 verkliga minuter före."""
    await hass.config.async_set_time_zone("Europe/Stockholm")
    freezer.move_to("2026-03-28T20:00:00+00:00")
    env = await make(subs=[sub(SID, "Motorvärmare 1", RELAY, live=False)], temp="-20")
    await env.call("add_departure", departure_at="2026-03-29 03:30:00")
    trip = env.s("sensor.motorvarmare_1_avresor").attributes["trips"][0]
    dep = dt_util.parse_datetime(trip["departure_at"])
    start = dt_util.parse_datetime(trip["start_at"])
    assert dep - start == timedelta(minutes=120)
    assert dt_util.as_local(dep).utcoffset() == timedelta(hours=2)
    assert dt_util.as_local(start).strftime("%H:%M") == "00:30"


# ---------------- enhetskoppling (0.2.1) ----------------

def _shelly_device(hass, entity_id, name, mac):
    from homeassistant.helpers import device_registry as dr, entity_registry as er
    shelly_entry = MockConfigEntry(domain="shelly", title=name)
    shelly_entry.add_to_hass(hass)
    dev = dr.async_get(hass).async_get_or_create(
        config_entry_id=shelly_entry.entry_id, identifiers={("shelly", mac)},
        connections={(dr.CONNECTION_NETWORK_MAC, mac.lower())}, manufacturer="Shelly",
        model="Shelly Pro 1PM", name=name)
    domain, obj = entity_id.split(".")
    prev = hass.states.get(entity_id)
    if prev:
        hass.states.async_remove(entity_id)
    reg = er.async_get(hass).async_get_or_create(domain, "shelly", f"{mac}-switch:0", suggested_object_id=obj,
                                                 config_entry=shelly_entry, device_id=dev.id)
    assert reg.entity_id == entity_id
    if prev:
        hass.states.async_set(entity_id, prev.state)
    return dev


def _our_entities(hass, entry):
    from homeassistant.helpers import entity_registry as er
    return er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)


async def test_entities_attached_to_relay_device(hass, make):
    dev = _shelly_device(hass, RELAY, "Motorvärmare 1", "AABBCCDDEEFF")
    env = await make()
    from homeassistant.helpers import device_registry as dr
    ents = _our_entities(hass, env.entry)
    assert len(ents) == 8
    assert {e.device_id for e in ents} == {dev.id}
    assert not [d for d in dr.async_entries_for_config_entry(dr.async_get(hass), env.entry.entry_id)
                if (DOMAIN, SID) in d.identifiers]
    shelly = dr.async_get(hass).async_get(dev.id)
    assert shelly.name == "Motorvärmare 1" and shelly.manufacturer == "Shelly"  # namnet ändras inte


async def test_testheater_without_relay_gets_own_device(hass, make):
    env = await make(subs=[sub(SID, "Motorvärmare 1", None, live=False)])
    from homeassistant.helpers import device_registry as dr
    own = next(d for d in dr.async_entries_for_config_entry(dr.async_get(hass), env.entry.entry_id)
               if (DOMAIN, SID) in d.identifiers)
    assert {e.device_id for e in _our_entities(hass, env.entry)} == {own.id}


async def test_choosing_relay_later_moves_entities_and_removes_own_device(hass, make):
    from homeassistant.helpers import device_registry as dr
    env = await make(subs=[sub(SID, "Motorvärmare 1", None, live=False)])
    ids_before = {e.unique_id: e.entity_id for e in _our_entities(hass, env.entry)}
    dev = _shelly_device(hass, RELAY, "Motorvärmare 1", "AABBCCDDEEFF")
    sub_obj = env.entry.subentries[SID]
    hass.config_entries.async_update_subentry(env.entry, sub_obj, data={**sub_obj.data, "relay_entity": RELAY})
    await hass.async_block_till_done()
    ents = _our_entities(hass, env.entry)
    assert {e.device_id for e in ents} == {dev.id}
    assert {e.unique_id: e.entity_id for e in ents} == ids_before  # entitets-id oförändrade
    assert not [d for d in dr.async_entries_for_config_entry(dr.async_get(hass), env.entry.entry_id)
                if (DOMAIN, SID) in d.identifiers]
    assert env.s("sensor.motorvarmare_1_status") is not None


async def test_removing_linked_heater_keeps_shelly_device(hass, make):
    from homeassistant.helpers import device_registry as dr
    dev = _shelly_device(hass, RELAY, "Motorvärmare 1", "AABBCCDDEEFF")
    env = await make()
    print("ENTITY_IDS", sorted(e.entity_id for e in _our_entities(hass, env.entry)))
    hass.config_entries.async_remove_subentry(env.entry, SID)
    await hass.async_block_till_done()
    assert dr.async_get(hass).async_get(dev.id) is not None
    assert not _our_entities(hass, env.entry)
    assert hass.states.get(RELAY) is not None


# ---------------- kalenderkopplingar (0.3) ----------------

CAL = "calendar.forskola"
CSID = "kal1"


def cal_sub(sid=CSID, title="Förskola", heaters=(SID,), **extra):
    data = {"calendar_entity": CAL, "heaters": list(heaters), "use_start": True,
            "travel_before_start": 15, "use_end": True, "travel_before_end": 15, **extra}
    return {"data": data, "subentry_id": sid, "subentry_type": "kalender", "title": title, "unique_id": None}


class FakeCalendar:
    def __init__(self, hass):
        from homeassistant.core import SupportsResponse
        self.events = []
        self.fail = False
        self.calls = 0
        hass.states.async_set(CAL, "off")

        async def handler(call):
            self.calls += 1
            if self.fail:
                raise HomeAssistantError("kalendern svarar inte")
            return {CAL: {"events": list(self.events)}}

        hass.services.async_register("calendar", "get_events", handler, supports_response=SupportsResponse.ONLY)

    def add(self, start, end, summary="Lämning"):
        fmt = lambda v: v if isinstance(v, str) else dt_util.as_local(v).isoformat()
        self.events.append({"start": fmt(start), "end": fmt(end), "summary": summary})


@pytest.fixture
def cal(hass):
    return FakeCalendar(hass)


def trips(env, eid="sensor.motorvarmare_1_avresor"):
    return env.s(eid).attributes["trips"]


async def refresh(env):
    await env.hass.services.async_call(DOMAIN, "refresh_calendars", {}, blocking=True)
    await env.hass.async_block_till_done()


async def test_calendar_start_and_end_with_travel_time(hass, make, cal):
    now = dt_util.now().replace(second=0, microsecond=0)
    start, end = now + timedelta(hours=5), now + timedelta(hours=13)
    cal.add(start, end, "Förskola")
    env = await make(subs=[sub(SID, "Motorvärmare 1", RELAY, live=False), cal_sub()])
    rows = trips(env)
    assert [dt_util.parse_datetime(r["departure_at"]) for r in rows] == [
        start - timedelta(minutes=15), end - timedelta(minutes=15)]
    assert [r["label"] for r in rows] == ["Förskola", "Förskola (slut)"]
    assert all(r["source"] == "calendar" and r["calendar"] == "Förskola" for r in rows)
    assert env.s("sensor.motorvarmare_1_avresor").state == "2"
    # samma läsning igen ger inga dubbletter
    await refresh(env)
    assert len(trips(env)) == 2


async def test_calendar_only_start_and_all_day_ignored(hass, make, cal):
    now = dt_util.now()
    cal.add(now + timedelta(hours=3), now + timedelta(hours=4))
    day = (now + timedelta(days=1)).date()
    cal.add(day.isoformat(), (day + timedelta(days=1)).isoformat(), "Heldag")
    env = await make(subs=[sub(SID, "Motorvärmare 1", RELAY, live=False), cal_sub(use_end=False, travel_before_start=0)])
    rows = trips(env)
    assert len(rows) == 1 and rows[0]["label"] == "Lämning"


async def test_calendar_need_and_purge_after_60(hass, make, cal, freezer):
    now = dt_util.now()
    cal.add(now + timedelta(minutes=45), now + timedelta(hours=6))  # avresa om 30 min, 0 °C -> 60 min
    env = await make(subs=[sub(SID, "Motorvärmare 1", RELAY), cal_sub()])
    assert env.s("binary_sensor.motorvarmare_1_varmebehov").state == "on"
    assert len(env.on) == 1
    await env.relay("on")
    await env.tick(freezer, timedelta(minutes=30 + 59))
    assert len(trips(env)) == 2  # ligger kvar till avresa + 60
    await env.tick(freezer, timedelta(minutes=1, seconds=30))
    assert len(trips(env)) == 1
    # En senare läsning lägger inte tillbaka den passerade avresan
    await refresh(env)
    assert len(trips(env)) == 1


async def test_calendar_event_removed_before_start_drops_trip(hass, make, cal):
    now = dt_util.now()
    cal.add(now + timedelta(hours=5), now + timedelta(hours=6))
    env = await make(subs=[sub(SID, "Motorvärmare 1", RELAY, live=False), cal_sub(use_end=False)])
    assert len(trips(env)) == 1
    cal.events.clear()
    await refresh(env)
    assert trips(env) == []


async def test_calendar_event_removed_after_start_keeps_heating(hass, make, cal):
    now = dt_util.now()
    cal.add(now + timedelta(minutes=30), now + timedelta(hours=6))
    env = await make(subs=[sub(SID, "Motorvärmare 1", RELAY, live=False), cal_sub(use_end=False)])
    assert env.s("binary_sensor.motorvarmare_1_varmebehov").state == "on"
    cal.events.clear()
    await refresh(env)
    assert len(trips(env)) == 1
    assert env.s("binary_sensor.motorvarmare_1_varmebehov").state == "on"


async def test_calendar_read_failure_keeps_trips(hass, make, cal):
    now = dt_util.now()
    cal.add(now + timedelta(hours=5), now + timedelta(hours=6))
    env = await make(subs=[sub(SID, "Motorvärmare 1", RELAY, live=False), cal_sub(use_end=False)])
    cal.fail = True
    await refresh(env)
    assert len(trips(env)) == 1


async def test_calendar_state_change_triggers_read(hass, make, cal):
    env = await make(subs=[sub(SID, "Motorvärmare 1", RELAY, live=False), cal_sub(use_end=False)])
    assert trips(env) == []
    now = dt_util.now()
    cal.add(now + timedelta(hours=5), now + timedelta(hours=6))
    hass.states.async_set(CAL, "on")
    await hass.async_block_till_done()
    assert len(trips(env)) == 1


async def test_calendar_periodic_read(hass, make, cal, freezer):
    env = await make(subs=[sub(SID, "Motorvärmare 1", RELAY, live=False), cal_sub(use_end=False)])
    now = dt_util.now()
    cal.add(now + timedelta(hours=5), now + timedelta(hours=6))
    await env.tick(freezer, timedelta(minutes=5, seconds=5))
    assert len(trips(env)) == 1


async def test_skip_calendar_trip_no_need_and_survives_read(hass, make, cal):
    now = dt_util.now()
    cal.add(now + timedelta(minutes=30), now + timedelta(hours=6))
    env = await make(subs=[sub(SID, "Motorvärmare 1", RELAY), cal_sub(use_end=False)])
    assert env.s("binary_sensor.motorvarmare_1_varmebehov").state == "on"
    await env.relay("on")
    tid = trips(env)[0]["id"]
    await env.call("skip_departure", trip_id=tid)
    assert env.s("binary_sensor.motorvarmare_1_varmebehov").state == "off"
    assert len(env.off) == 1
    assert trips(env)[0]["skipped"] is True
    assert env.s("sensor.motorvarmare_1_avresor").state == "0"
    await refresh(env)
    assert trips(env)[0]["skipped"] is True
    await env.call("unskip_departure", trip_id=tid)
    assert env.s("binary_sensor.motorvarmare_1_varmebehov").state == "on"


async def test_skipped_trip_not_next_start(hass, make, cal):
    now = dt_util.now()
    cal.add(now + timedelta(hours=5), now + timedelta(hours=6))
    env = await make(subs=[sub(SID, "Motorvärmare 1", RELAY, live=False), cal_sub(use_end=False)])
    assert env.s("sensor.motorvarmare_1_nasta_start").state not in ("unknown", None)
    await env.call("skip_departure", trip_id=trips(env)[0]["id"])
    assert env.s("sensor.motorvarmare_1_nasta_start").state == "unknown"


async def test_calendar_trip_edit_rejected_remove_skips(hass, make, cal):
    now = dt_util.now()
    cal.add(now + timedelta(hours=5), now + timedelta(hours=6))
    env = await make(subs=[sub(SID, "Motorvärmare 1", RELAY, live=False), cal_sub(use_end=False)])
    tid = trips(env)[0]["id"]
    with pytest.raises(HomeAssistantError):
        await env.call("edit_departure", trip_id=tid, departure_at=(now + timedelta(hours=7)).isoformat())
    await env.call("remove_departure", trip_id=tid)
    assert trips(env)[0]["skipped"] is True


async def test_manual_and_calendar_trips_coexist(hass, make, cal):
    now = dt_util.now()
    cal.add(now + timedelta(hours=5), now + timedelta(hours=6))
    env = await make(subs=[sub(SID, "Motorvärmare 1", RELAY, live=False), cal_sub(use_end=False)])
    await env.call("add_departure", departure_at=(now + timedelta(hours=2)).isoformat())
    await env.call("add_departure", departure_at=(now + timedelta(hours=3)).isoformat())
    await refresh(env)
    rows = trips(env)
    assert [r["source"] for r in rows] == ["manual", "manual", "calendar"]


async def test_calendar_to_two_heaters(hass, make, cal):
    now = dt_util.now()
    cal.add(now + timedelta(hours=5), now + timedelta(hours=6))
    env = await make(subs=[sub(SID, "Motorvärmare 1", RELAY, live=False), sub(SID2, "Motorvärmare 2", RELAY2, live=False),
                           cal_sub(heaters=(SID, SID2), use_end=False)])
    assert len(trips(env)) == 1
    assert len(trips(env, "sensor.motorvarmare_2_avresor")) == 1
    # Överhoppning gäller bara det uttag där den görs
    await env.call("skip_departure", trip_id=trips(env)[0]["id"])
    assert trips(env, "sensor.motorvarmare_2_avresor")[0]["skipped"] is False


async def test_calendar_subentry_flow_and_validation(hass, make, cal):
    env = await make()
    entry = env.entry
    r = await hass.config_entries.subentries.async_init((entry.entry_id, "kalender"), context={"source": "user"})
    assert r["type"] is FlowResultType.FORM
    base = {"name": "Förskola", "calendar_entity": CAL, "heaters": [SID], "use_start": True,
            "travel_before_start": 15, "use_end": True, "travel_before_end": 15}
    r = await hass.config_entries.subentries.async_configure(r["flow_id"], {**base, "heaters": []})
    assert r["errors"] == {"heaters": "no_heater"}
    r = await hass.config_entries.subentries.async_configure(r["flow_id"], {**base, "use_start": False, "use_end": False})
    assert r["errors"] == {"use_start": "no_departure_point"}
    now = dt_util.now()
    cal.add(now + timedelta(hours=5), now + timedelta(hours=6))
    r = await hass.config_entries.subentries.async_configure(r["flow_id"], base)
    assert r["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert len(trips(env)) == 2
    # Nytt uttag räknar bara uttag i förslaget till namn
    r = await hass.config_entries.subentries.async_init((entry.entry_id, "uttag"), context={"source": "user"})
    assert r["data_schema"]({"temperature_entity": TEMP})["name"] == "Motorvärmare 2"


async def test_calendar_flow_aborts_without_heaters(hass, make, cal):
    env = await make(subs=[])
    r = await hass.config_entries.subentries.async_init((env.entry.entry_id, "kalender"), context={"source": "user"})
    assert r["type"] is FlowResultType.ABORT and r["reason"] == "no_heaters"


async def test_removing_calendar_link_drops_unstarted_trips(hass, make, cal):
    now = dt_util.now()
    cal.add(now + timedelta(hours=5), now + timedelta(hours=6))
    env = await make(subs=[sub(SID, "Motorvärmare 1", RELAY, live=False), cal_sub(use_end=False)])
    await env.call("add_departure", departure_at=(now + timedelta(hours=2)).isoformat())
    assert len(trips(env)) == 2
    hass.config_entries.async_remove_subentry(env.entry, CSID)
    await hass.async_block_till_done()
    rows = trips(env)
    assert [r["source"] for r in rows] == ["manual"]


async def test_calendar_trips_persist_over_restart(hass, make, cal, hass_storage):
    now = dt_util.now()
    cal.add(now + timedelta(hours=5), now + timedelta(hours=6))
    env = await make(subs=[sub(SID, "Motorvärmare 1", RELAY, live=False), cal_sub(use_end=False)])
    await env.call("skip_departure", trip_id=trips(env)[0]["id"])
    cal.fail = True  # kalendern inte redo efter omstart
    assert await hass.config_entries.async_reload(env.entry.entry_id)
    await hass.async_block_till_done()
    assert trips(env)[0]["skipped"] is True
