"""Konstanter för Motorvärmare."""
from datetime import timedelta

DOMAIN = "motorvarmare"
PLATFORMS = ["binary_sensor", "button", "sensor"]
SUBENTRY_TYPE = "uttag"
CALENDAR_SUBENTRY_TYPE = "kalender"

STORAGE_KEY = "motorvarmare.state"
STORAGE_VERSION = 1

# Konfiguration per uttag (subentry data)
CONF_TEMPERATURE = "temperature_entity"
CONF_RELAY = "relay_entity"
CONF_LIVE = "live_control"
CONF_AUTO_OFF = "auto_off_minutes"
CONF_BASE = "base_minutes"
CONF_SLOPE = "minutes_per_degree"
CONF_MIN = "minimum_minutes"
CONF_MAX = "maximum_minutes"
CONF_FALLBACK = "fallback_minutes"
CONF_CACHE = "temperature_cache_minutes"
CONF_HEATER_NOTIFY = "notify_services"  # larmmottagare för just detta uttag; tom = integrationens gemensamma

DEFAULTS = {
    CONF_LIVE: False,
    CONF_AUTO_OFF: 240,
    CONF_BASE: 60,
    CONF_SLOPE: 3.0,
    CONF_MIN: 0,
    CONF_MAX: 240,
    CONF_FALLBACK: 180,
    CONF_CACHE: 30,
}

# Konfiguration per kalenderkoppling (subentry data)
CONF_CALENDAR = "calendar_entity"
CONF_HEATERS = "heaters"
CONF_USE_START = "use_start"
CONF_TRAVEL_START = "travel_before_start"
CONF_USE_END = "use_end"
CONF_TRAVEL_END = "travel_before_end"
CONF_START_DIRECTION = "start_direction"
CONF_END_DIRECTION = "end_direction"
CONF_FILTER = "event_filter"
CONF_KEYWORDS = "keywords"  # {uttagets subentry_id: text}

DIRECTION_BEFORE = "before"
DIRECTION_AFTER = "after"
FILTER_ALL = "all"
FILTER_KEYWORD = "keyword"

CALENDAR_DEFAULTS = {
    CONF_USE_START: True,
    CONF_TRAVEL_START: 0,
    CONF_USE_END: False,
    CONF_TRAVEL_END: 0,
    CONF_START_DIRECTION: DIRECTION_BEFORE,
    CONF_END_DIRECTION: DIRECTION_BEFORE,
    CONF_FILTER: FILTER_ALL,
    CONF_KEYWORDS: {},
}

# Konfiguration för hela integrationen (entry options)
CONF_NOTIFY = "notify_service"
CONF_ALLOWED_CALENDARS = "allowed_calendars"  # tom lista = alla kalendrar

# Fasta beslut
AFTER_DEPARTURE = timedelta(minutes=60)  # behov kvar till avresa + 60 min (beslut)
RELAY_CONFIRM = timedelta(seconds=30)  # tid för relä att bekräfta PÅ, och sammanhängande AV-tid före spärr
UNAVAILABLE_WARN = timedelta(minutes=2)  # relä otillgängligt under behov -> varning
AUTO_OFF_MARGIN = timedelta(minutes=5)  # integrationen slår själv av så här länge före Shellyns Auto Off
TICK = timedelta(seconds=15)
TEMP_VALID = (-60.0, 60.0)
FORCE_CHOICES = (15, 30, 60, 120, 240)
CALENDAR_REFRESH = timedelta(minutes=5)  # kalendern läses om så här ofta (och vid ändring)
CALENDAR_LOOKBACK = timedelta(hours=2)
CALENDAR_LOOKAHEAD = timedelta(days=2)
