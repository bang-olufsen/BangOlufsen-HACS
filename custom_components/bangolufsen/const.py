"""Constants for the Bang & Olufsen integration."""
# pylint: disable=invalid-name too-many-instance-attributes too-few-public-methods

from __future__ import annotations

from enum import Enum
from typing import Final, cast

from mozart_api.models import (
    BatteryState,
    BeoRemoteButton,
    ButtonEvent,
    ListeningModeProps,
    PlaybackContentMetadata,
    PlaybackError,
    PlaybackProgress,
    PowerStateEnum,
    Preset,
    RenderingState,
    SoftwareUpdateState,
    SoundSettings,
    Source,
    SourceArray,
    SourceTypeEnum,
    SpeakerGroupOverview,
    VolumeLevel,
    VolumeMute,
    VolumeState,
    WebsocketNotificationTag,
)
from mozart_api.mozart_client import MozartClient

from homeassistant.backports.enum import StrEnum
from homeassistant.components.media_player import MediaPlayerState, MediaType
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceEntry
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import DeviceInfo, Entity


class ArtSizeEnum(Enum):
    """Enum used for sorting images that have size defined by a string."""

    small = 1
    medium = 2
    large = 3


class SourceEnum(StrEnum):
    """Enum used for associating device source ids with friendly names. May not include all sources."""

    uriStreamer = "Audio Streamer"
    bluetooth = "Bluetooth"
    airPlay = "AirPlay"
    chromeCast = "Chromecast built-in"
    spotify = "Spotify Connect"
    generator = "Tone Generator"
    lineIn = "Line-In"
    spdif = "Optical"
    netRadio = "B&O Radio"
    local = "Local"
    dlna = "DLNA"
    qplay = "QPlay"
    wpl = "Wireless Powerlink"
    pl = "Powerlink"
    tv = "TV"
    deezer = "Deezer"
    beolink = "Networklink"
    tidalConnect = "Tidal Connect"


class RepeatEnum(StrEnum):
    """Enum used for translating device repeat settings to Home Assistant settings."""

    all = "all"
    one = "track"
    off = "none"


class StateEnum(StrEnum):
    """Enum used for translating device states to Home Assistant states."""

    # Playback states
    started = MediaPlayerState.PLAYING
    buffering = MediaPlayerState.PLAYING
    idle = MediaPlayerState.IDLE
    paused = MediaPlayerState.PAUSED
    stopped = MediaPlayerState.PAUSED
    ended = MediaPlayerState.PAUSED
    error = MediaPlayerState.IDLE
    # A devices initial state is "unknown" and should be treated as "idle"
    unknown = MediaPlayerState.IDLE

    # Power states
    networkStandby = MediaPlayerState.IDLE


# Media types for play_media
class BangOlufsenMediaType(StrEnum):
    """Bang & Olufsen specific media types."""

    FAVOURITE = "favourite"
    DEEZER = "deezer"
    RADIO = "radio"
    TTS = "provider"


# Proximity detection for binary_sensor
class ProximityEnum(Enum):
    """Proximity detection mapping.."""

    proximityPresenceDetected = True
    proximityPresenceNotDetected = False


class ModelEnum(StrEnum):
    """Enum for compatible model names."""

    beolab_28 = "BeoLab 28"
    beosound_2 = "Beosound 2 3rd Gen"
    beosound_a5 = "Beosound A5"
    beosound_a9 = "Beosound A9 5th Gen"
    beosound_balance = "Beosound Balance"
    beosound_emerge = "Beosound Emerge"
    beosound_level = "Beosound Level"
    beosound_theatre = "Beosound Theatre"


class EntityEnum(StrEnum):
    """Enum for accessing and storing the entities in hass."""

    BINARY_SENSORS = "binary_sensors"
    COORDINATOR = "coordinator"
    MEDIA_PLAYER = "media_player"
    NUMBERS = "numbers"
    FAVOURITES = "favourites"
    SENSORS = "sensors"
    SWITCHES = "switches"
    TEXT = "text"
    SELECTS = "selects"


# Dispatcher events
class WebSocketNotification(StrEnum):
    """Enum for WebSocket notification types."""

    ACTIVE_LISTENING_MODE: Final[str] = "active_listening_mode"
    ACTIVE_SPEAKER_GROUP: Final[str] = "active_speaker_group"
    ALARM_TRIGGERED: Final[str] = "alarm_triggered"
    BATTERY: Final[str] = "battery"
    BEOLINK_EXPERIENCES_RESULT: Final[str] = "beolink_experiences_result"
    BEOLINK_JOIN_RESULT: Final[str] = "beolink_join_result"
    BEO_REMOTE_BUTTON: Final[str] = "beo_remote_button"
    BUTTON: Final[str] = "button"
    CURTAINS: Final[str] = "curtains"
    PLAYBACK_ERROR: Final[str] = "playback_error"
    PLAYBACK_METADATA: Final[str] = "playback_metadata"
    PLAYBACK_PROGRESS: Final[str] = "playback_progress"
    PLAYBACK_SOURCE: Final[str] = "playback_source"
    PLAYBACK_STATE: Final[str] = "playback_state"
    POWER_STATE: Final[str] = "power_state"
    ROLE: Final[str] = "role"
    SOFTWARE_UPDATE_STATE: Final[str] = "software_update_state"
    SOUND_SETTINGS: Final[str] = "sound_settings"
    SOURCE_CHANGE: Final[str] = "source_change"
    VOLUME: Final[str] = "volume"

    # Sub-notifications
    NOTIFICATION: Final[str] = "notification"
    PROXIMITY: Final[str] = "proximity"
    BEOLINK: Final[str] = "beolink"
    REMOTE_MENU_CHANGED: Final[str] = "remoteMenuChanged"
    CONFIGURATION: Final[str] = "configuration"
    BLUETOOTH_DEVICES: Final[str] = "bluetooth"
    REMOTE_CONTROL_DEVICES: Final[str] = "remoteControlDevices"

    ALL: Final[str] = "all"


class SupportEnum(Enum):
    """Enum for storing compatibility of devices."""

    PROXIMITY_SENSOR = (
        ModelEnum.beolab_28,
        ModelEnum.beosound_2,
        ModelEnum.beosound_balance,
        ModelEnum.beosound_level,
        ModelEnum.beosound_theatre,
    )

    HOME_CONTROL = (ModelEnum.beosound_theatre,)


DOMAIN: Final[str] = "bangolufsen"

# Default values for configuration.
DEFAULT_HOST: Final[str] = "192.168.1.1"
DEFAULT_DEFAULT_VOLUME: Final[int] = 40
DEFAULT_MAX_VOLUME: Final[int] = 100
DEFAULT_VOLUME_STEP: Final[int] = 5
DEFAULT_MODEL: Final[str] = ModelEnum.beosound_balance

# Acceptable ranges for configuration.
DEFAULT_VOLUME_RANGE: Final[range] = range(1, (70 + 1), 1)
MAX_VOLUME_RANGE: Final[range] = range(20, (100 + 1), 1)
VOLUME_STEP_RANGE: Final[range] = range(1, (20 + 1), 1)

# Abort reasons for configuration.
API_EXCEPTION: Final[str] = "api_exception"
MAX_RETRY_ERROR: Final[str] = "max_retry_error"
NEW_CONNECTION_ERROR: Final[str] = "new_connection_error"
NO_DEVICE: Final[str] = "no_device"
VALUE_ERROR: Final[str] = "value_error"

# Configuration.
CONF_DEFAULT_VOLUME: Final = "default_volume"
CONF_MAX_VOLUME: Final = "max_volume"
CONF_VOLUME_STEP: Final = "volume_step"
CONF_SERIAL_NUMBER: Final = "serial_number"
CONF_BEOLINK_JID: Final = "jid"

# Models to choose from in manual configuration.
COMPATIBLE_MODELS: list[str] = [x.value for x in ModelEnum]

# Attribute names for zeroconf discovery.
ATTR_TYPE_NUMBER: Final[str] = "tn"
ATTR_SERIAL_NUMBER: Final[str] = "sn"
ATTR_ITEM_NUMBER: Final[str] = "in"
ATTR_FRIENDLY_NAME: Final[str] = "fn"

# Power states.
BANGOLUFSEN_ON: Final[str] = "on"

VALID_MEDIA_TYPES: Final[tuple] = (
    BangOlufsenMediaType.FAVOURITE,
    BangOlufsenMediaType.DEEZER,
    BangOlufsenMediaType.RADIO,
    BangOlufsenMediaType.TTS,
    MediaType.MUSIC,
    MediaType.URL,
    MediaType.CHANNEL,
)

# Playback states for playing and not playing
PLAYING: Final[tuple] = ("started", "buffering", BANGOLUFSEN_ON)
NOT_PLAYING: Final[tuple] = ("idle", "paused", "stopped", "ended", "unknown", "error")

# Sources on the device that should not be selectable by the user
HIDDEN_SOURCE_IDS: Final[tuple] = (
    "airPlay",
    "bluetooth",
    "chromeCast",
    "generator",
    "local",
    "dlna",
    "qplay",
    "wpl",
    "pl",
    "beolink",
    "classicsAdapter",
    "usbIn",
)

# Fallback sources to use in case of API failure.
FALLBACK_SOURCES: Final[SourceArray] = SourceArray(
    items=[
        Source(
            id="uriStreamer",
            is_enabled=True,
            is_playable=False,
            name="Audio Streamer",
            type=SourceTypeEnum("uriStreamer"),
        ),
        Source(
            id="bluetooth",
            is_enabled=True,
            is_playable=False,
            name="Bluetooth",
            type=SourceTypeEnum("bluetooth"),
        ),
        Source(
            id="spotify",
            is_enabled=True,
            is_playable=False,
            name="Spotify Connect",
            type=SourceTypeEnum("spotify"),
        ),
        Source(
            id="lineIn",
            is_enabled=True,
            is_playable=True,
            name="Line-In",
            type=SourceTypeEnum("lineIn"),
        ),
        Source(
            id="spdif",
            is_enabled=True,
            is_playable=True,
            name="Optical",
            type=SourceTypeEnum("spdif"),
        ),
        Source(
            id="netRadio",
            is_enabled=True,
            is_playable=True,
            name="B&O Radio",
            type=SourceTypeEnum("netRadio"),
        ),
        Source(
            id="deezer",
            is_enabled=True,
            is_playable=True,
            name="Deezer",
            type=SourceTypeEnum("deezer"),
        ),
        Source(
            id="tidalConnect",
            is_enabled=True,
            is_playable=True,
            name="Tidal Connect",
            type=SourceTypeEnum("tidalConnect"),
        ),
    ]
)


# Device trigger events
BANGOLUFSEN_EVENT: Final[str] = f"{DOMAIN}_event"
BANGOLUFSEN_WEBSOCKET_EVENT: Final[str] = f"{DOMAIN}_websocket_event"


CONNECTION_STATUS: Final[str] = "CONNECTION_STATUS"
START_WEBSOCKET: Final[str] = "START_WEBSOCKET"
STOP_WEBSOCKET: Final[str] = "STOP_WEBSOCKET"
BEOLINK_LEADER_COMMAND: Final[str] = "BEOLINK_LEADER_COMMAND"
BEOLINK_LISTENER_COMMAND: Final[str] = "BEOLINK_LISTENER_COMMAND"
BEOLINK_VOLUME: Final[str] = "BEOLINK_VOLUME"


# Misc.
NO_METADATA: Final[tuple] = (None, "", 0)

# Valid commands and their expected parameter type for beolink_command service
FLOAT_PARAMETERS: Final[tuple] = ("set_volume_level", "media_seek", float)
BOOL_PARAMETERS: Final[tuple] = ("mute_volume", bool)
STR_PARAMETERS: Final[tuple] = ("select_source", str)
NONE_PARAMETERS: Final[tuple] = (
    "volume_up",
    "volume_down",
    "media_play_pause",
    "media_pause",
    "media_play",
    "media_stop",
    "media_next_track",
    "media_previous_track",
    "toggle",
    None,
)

# Tuple of accepted commands for input validation
ACCEPTED_COMMANDS: Final[tuple] = (
    FLOAT_PARAMETERS[:-1]
    + BOOL_PARAMETERS[:-1]
    + STR_PARAMETERS[:-1]
    + NONE_PARAMETERS[:-1]
)

# Tuple of all commands and their types for executing commands.
ACCEPTED_COMMANDS_LISTS: Final[tuple] = (
    FLOAT_PARAMETERS,
    BOOL_PARAMETERS,
    STR_PARAMETERS,
    NONE_PARAMETERS,
)


def get_device(hass: HomeAssistant | None, unique_id: str) -> DeviceEntry | None:
    """Get the device."""
    if not isinstance(hass, HomeAssistant):
        return None

    device_registry = dr.async_get(hass)
    device = cast(DeviceEntry, device_registry.async_get_device({(DOMAIN, unique_id)}))
    return device


def generate_favourite_attributes(
    favourite: Preset,
) -> dict[str, str | int | dict[str, str | bool]]:
    """Generate extra state attributes for a favourite."""
    favourite_attribute: dict[str, str | int | dict[str, str | bool]] = {}

    # Ensure that favourites with volume are properly shown.
    for action in favourite.action_list:
        if action.type == "volume":
            favourite_attribute["volume"] = action.volume_level

        else:
            deezer_user_id = action.deezer_user_id
            favourite_type = action.type
            favourite_queue = action.queue_item

            # Add Deezer as "source".
            if (
                favourite_type == "deezerFlow"
                or favourite_type == "playQueue"
                and favourite_queue.provider.value == "deezer"
            ):
                favourite_attribute["source"] = SourceEnum.deezer

            # Add netradio as "source".
            elif favourite_type == "radio":
                favourite_attribute["source"] = SourceEnum.netRadio

            # Add the source name if it is not none.
            elif favourite.source is not None:
                favourite_attribute["source"] = SourceEnum[favourite.source.value].value

            # Add title if available.
            if favourite.title is not None:
                favourite_attribute["name"] = favourite.title

            # Ensure that all favourites have a "name".
            if "name" not in favourite_attribute:
                favourite_attribute["name"] = favourite_attribute["source"]

            # Add Deezer flow.
            if favourite_type == "deezerFlow":
                if deezer_user_id is not None:
                    favourite_attribute["id"] = int(deezer_user_id)

            # Add Deezer playlist "uri" and name
            elif favourite_type == "playQueue":
                favourite_attribute["id"] = favourite_queue.uri

                # Add queue settings for Deezer queues.
                if action.queue_settings:
                    favourite_attribute["queue_settings"] = {
                        "repeat": action.queue_settings.repeat,
                        "shuffle": action.queue_settings.shuffle,
                    }

    return favourite_attribute


class BangOlufsenVariables:
    """Shared variables for various classes."""

    def __init__(self, entry: ConfigEntry) -> None:
        """Initialize the object."""

        # get the input from the config entry.
        self.entry: ConfigEntry = entry

        # Set the configuration variables.
        self._host: str = self.entry.data[CONF_HOST]
        self._name: str = self.entry.data[CONF_NAME]
        self._unique_id: str = cast(str, self.entry.unique_id)

        self._client: MozartClient = MozartClient(
            host=self._host, websocket_reconnect=True
        )

        # Objects that get directly updated by notifications.
        self._active_listening_mode = ListeningModeProps()
        self._active_speaker_group = SpeakerGroupOverview(
            friendly_name="", id="", is_deleteable=False
        )
        self._battery: BatteryState = BatteryState()
        self._beo_remote_button: BeoRemoteButton = BeoRemoteButton()
        self._button: ButtonEvent = ButtonEvent()
        self._notification: WebsocketNotificationTag = WebsocketNotificationTag()
        self._playback_error: PlaybackError = PlaybackError()
        self._playback_metadata: PlaybackContentMetadata = PlaybackContentMetadata()
        self._playback_progress: PlaybackProgress = PlaybackProgress(total_duration=0)
        self._playback_source: Source = Source()
        self._playback_state: RenderingState = RenderingState()
        self._power_state: PowerStateEnum = PowerStateEnum()
        self._software_update_state: SoftwareUpdateState = SoftwareUpdateState()
        self._sound_settings: SoundSettings = SoundSettings()
        self._source_change: Source = Source()
        self._volume: VolumeState = VolumeState(
            level=VolumeLevel(level=0), muted=VolumeMute(muted=False)
        )


class BangOlufsenEntity(Entity, BangOlufsenVariables):
    """Base Entity for BangOlufsen entities."""

    def __init__(self, entry: ConfigEntry) -> None:
        """Initialize the object."""
        BangOlufsenVariables.__init__(self, entry)
        self._dispatchers: list = []

        self._attr_should_poll = False
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, self._unique_id)})
        self._attr_device_class = None
        self._attr_entity_category = None

    async def async_added_to_hass(self) -> None:
        """Turn on the dispatchers."""
        self._dispatchers = [
            async_dispatcher_connect(
                self.hass,
                f"{self._unique_id}_{CONNECTION_STATUS}",
                self._update_connection_state,
            )
        ]

    async def async_will_remove_from_hass(self) -> None:
        """Turn off the dispatchers."""
        for dispatcher in self._dispatchers:
            dispatcher()

    async def _update_connection_state(self, connection_state: bool) -> None:
        """Update entity connection state."""
        self._attr_available = connection_state

        self.async_write_ha_state()
