"""Media player entity for the Bang & Olufsen integration."""
from __future__ import annotations

import asyncio
from datetime import datetime
import json
import logging
from typing import Any, cast

from mozart_api.exceptions import ApiException
from mozart_api.models import (
    Art,
    BeolinkLeader,
    BeolinkListener,
    OverlayPlayRequest,
    OverlayPlayRequestTextToSpeechTextToSpeech,
    PlaybackContentMetadata,
    PlaybackError,
    PlaybackProgress,
    PlayQueueItem,
    PlayQueueItemType,
    PlayQueueSettings,
    RenderingState,
    SoftwareUpdateState,
    SoftwareUpdateStatus,
    Source,
    Uri,
    UserFlow,
    VolumeLevel,
    VolumeMute,
    VolumeSettings,
    VolumeState,
    WebsocketNotificationTag,
)
from mozart_api.mozart_client import check_valid_jid
import voluptuous as vol

from homeassistant.components import media_source
from homeassistant.components.media_player import (
    ATTR_MEDIA_EXTRA,
    BrowseMedia,
    MediaPlayerDeviceClass,
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
    MediaType,
    RepeatMode,
    async_process_play_media_url,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_MODEL, Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import (
    config_validation as cv,
    device_registry as dr,
    entity_platform,
    entity_registry as er,
)
from homeassistant.helpers.dispatcher import (
    async_dispatcher_connect,
    async_dispatcher_send,
)
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.entity_registry import RegistryEntry
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util.dt import utcnow

from .const import (
    ACCEPTED_COMMANDS,
    ACCEPTED_COMMANDS_LISTS,
    BEOLINK_LEADER_COMMAND,
    BEOLINK_LISTENER_COMMAND,
    BEOLINK_VOLUME,
    CLEANUP,
    CONF_BEOLINK_JID,
    CONF_DEFAULT_VOLUME,
    CONF_MAX_VOLUME,
    CONF_VOLUME_STEP,
    CONNECTION_STATUS,
    DOMAIN,
    FALLBACK_SOURCES,
    HASS_CONTROLLER,
    HASS_MEDIA_PLAYER,
    HIDDEN_SOURCE_IDS,
    NO_METADATA,
    VALID_MEDIA_TYPES,
    WS_REMOTE_CONTROL_AVAILABLE,
    ArtSizeEnum,
    BangOlufsenMediaType,
    BangOlufsenVariables,
    RepeatEnum,
    SourceEnum,
    StateEnum,
    WebSocketNotification,
)
from .coordinator import BangOlufsenCoordinator

_LOGGER = logging.getLogger(__name__)

BANGOLUFSEN_FEATURES = (
    MediaPlayerEntityFeature.PAUSE
    | MediaPlayerEntityFeature.SEEK
    | MediaPlayerEntityFeature.VOLUME_SET
    | MediaPlayerEntityFeature.VOLUME_MUTE
    | MediaPlayerEntityFeature.PREVIOUS_TRACK
    | MediaPlayerEntityFeature.NEXT_TRACK
    | MediaPlayerEntityFeature.PLAY_MEDIA
    | MediaPlayerEntityFeature.VOLUME_STEP
    | MediaPlayerEntityFeature.SELECT_SOURCE
    | MediaPlayerEntityFeature.STOP
    | MediaPlayerEntityFeature.CLEAR_PLAYLIST
    | MediaPlayerEntityFeature.PLAY
    | MediaPlayerEntityFeature.SHUFFLE_SET
    | MediaPlayerEntityFeature.BROWSE_MEDIA
    | MediaPlayerEntityFeature.REPEAT_SET
    | MediaPlayerEntityFeature.GROUPING
)


PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up a Media Player entity from config entry."""
    device = hass.data[DOMAIN][config_entry.unique_id][HASS_MEDIA_PLAYER]
    async_add_entities([device])

    # Register services.
    platform = entity_platform.async_get_current_platform()

    platform.async_register_entity_service(
        name="beolink_join",
        schema={
            vol.Optional("beolink_jid"): vol.All(
                vol.Coerce(type=cv.string),
                vol.Length(min=47, max=47),
            ),
        },
        func="async_beolink_join",
    )

    platform.async_register_entity_service(
        name="beolink_expand",
        schema={
            vol.Required("beolink_jids"): vol.All(
                cv.ensure_list,
                [
                    vol.All(
                        vol.Coerce(type=cv.string),
                        vol.Length(min=47, max=47),
                    )
                ],
            )
        },
        func="async_beolink_expand",
    )

    platform.async_register_entity_service(
        name="beolink_unexpand",
        schema={
            vol.Required("beolink_jids"): vol.All(
                cv.ensure_list,
                [
                    vol.All(
                        vol.Coerce(type=cv.string),
                        vol.Length(min=47, max=47),
                    )
                ],
            )
        },
        func="async_beolink_unexpand",
    )

    platform.async_register_entity_service(
        name="beolink_leave",
        schema=None,
        func="async_beolink_leave",
    )

    platform.async_register_entity_service(
        name="beolink_allstandby",
        schema=None,
        func="async_beolink_allstandby",
    )

    platform.async_register_entity_service(
        name="beolink_set_volume",
        schema={vol.Required("volume_level"): cv.string},
        func="async_beolink_set_volume",
    )

    platform.async_register_entity_service(
        name="beolink_leader_command",
        schema={
            vol.Required("command"): vol.In(ACCEPTED_COMMANDS),
            vol.Optional("parameter"): cv.string,
        },
        func="async_beolink_leader_command",
    )

    platform.async_register_entity_service(
        name="overlay_audio",
        schema={
            vol.Optional("uri"): cv.string,
            vol.Optional("absolute_volume"): vol.All(
                vol.Coerce(int),
                vol.Range(min=0, max=100),
            ),
            vol.Optional("volume_offset"): vol.All(
                vol.Coerce(int),
                vol.Range(min=0, max=100),
            ),
            vol.Optional("tts"): cv.string,
            vol.Optional("tts_language"): cv.string,
        },
        func="async_overlay_audio",
    )


class BangOlufsenMediaPlayer(
    MediaPlayerEntity, BangOlufsenVariables, CoordinatorEntity
):
    """Representation of a media player."""

    def __init__(self, entry: ConfigEntry, coordinator: BangOlufsenCoordinator) -> None:
        """Initialize the media player."""
        MediaPlayerEntity.__init__(self)
        BangOlufsenVariables.__init__(self, entry)
        CoordinatorEntity.__init__(self, coordinator)

        # Static entity attributes
        self._attr_should_poll = False
        self._attr_device_class = MediaPlayerDeviceClass.SPEAKER
        self._attr_name = self._name
        self._attr_icon = "mdi:speaker-wireless"
        self._attr_supported_features = BANGOLUFSEN_FEATURES
        self._attr_unique_id = self._unique_id
        self._attr_group_members = []

        self._beolink_jid: str = self.entry.data[CONF_BEOLINK_JID]
        self._max_volume: int = self.entry.data[CONF_MAX_VOLUME]
        self._volume_step: int = self.entry.data[CONF_VOLUME_STEP]
        self._default_volume: int = self.entry.data[CONF_DEFAULT_VOLUME]
        self._model: str = self.entry.data[CONF_MODEL]

        # Misc. variables.
        self._friendly_name: str = ""
        self._state: MediaPlayerState | str = MediaPlayerState.IDLE
        self._media_image: Art = Art()
        self._last_update: datetime = datetime(1970, 1, 1, 0, 0, 0, 0)
        self._source_list: list[str] = []
        self._source_list_friendly: list[str] = []
        self._beolink_listeners: list[BeolinkListener] = []
        self._remote_leader: BeolinkLeader | None = None
        self._queue_settings: PlayQueueSettings = PlayQueueSettings()
        self._software_status: SoftwareUpdateStatus = SoftwareUpdateStatus(
            software_version="",
            state=SoftwareUpdateState(seconds_remaining=0, value="idle"),
        )

        # Extra state attributes.
        self._beolink_attribute: dict[str, dict] | None = None
        self._bluetooth_attribute: dict[str, dict] | None = None

    async def async_added_to_hass(self) -> None:
        """Turn on the dispatchers."""

        self._dispatchers = [
            async_dispatcher_connect(
                self.hass,
                f"{self._unique_id}_{CONNECTION_STATUS}",
                self._update_connection_state,
            ),
            async_dispatcher_connect(
                self.hass,
                f"{self._unique_id}_{WebSocketNotification.PLAYBACK_METADATA}",
                self._update_playback_metadata,
            ),
            async_dispatcher_connect(
                self.hass,
                f"{self._unique_id}_{WebSocketNotification.PLAYBACK_ERROR}",
                self._update_playback_error,
            ),
            async_dispatcher_connect(
                self.hass,
                f"{self._unique_id}_{WebSocketNotification.PLAYBACK_PROGRESS}",
                self._update_playback_progress,
            ),
            async_dispatcher_connect(
                self.hass,
                f"{self._unique_id}_{WebSocketNotification.PLAYBACK_STATE}",
                self._update_playback_state,
            ),
            async_dispatcher_connect(
                self.hass,
                f"{self._unique_id}_{WebSocketNotification.SOURCE_CHANGE}",
                self._update_source_change,
            ),
            async_dispatcher_connect(
                self.hass,
                f"{self._unique_id}_{WebSocketNotification.NOTIFICATION}",
                self._update_notification,
            ),
            async_dispatcher_connect(
                self.hass,
                f"{self._unique_id}_{WebSocketNotification.VOLUME}",
                self._update_volume,
            ),
            async_dispatcher_connect(
                self.hass,
                f"{self._beolink_jid}_{BEOLINK_LEADER_COMMAND}",
                self.async_beolink_leader_command,
            ),
            async_dispatcher_connect(
                self.hass,
                f"{self._beolink_jid}_{BEOLINK_LISTENER_COMMAND}",
                self.async_beolink_listener_command,
            ),
            async_dispatcher_connect(
                self.hass,
                f"{self._beolink_jid}_{BEOLINK_VOLUME}",
                self.async_beolink_set_volume,
            ),
        ]

        self.async_on_remove(
            self.coordinator.async_add_listener(self._update_coordinator_data)
        )

        # Initialize the entity and WebSocket notification listener
        await self.bangolufsen_init()

    async def async_will_remove_from_hass(self) -> None:
        """Turn off the WebSocket listener and dispatchers."""
        async_dispatcher_send(self.hass, f"{self._unique_id}_{CLEANUP}")

        for dispatcher in self._dispatchers:
            dispatcher()

    async def bangolufsen_init(self) -> bool:
        """Initialize network dependent variables."""
        # Get software version.
        self._software_status = self._client.get_softwareupdate_status(
            async_req=True
        ).get()

        # Update the device sw version
        device_registry = dr.async_get(self.hass)
        device = device_registry.async_get_device(
            identifiers={(DOMAIN, self._unique_id)}
        )

        # Update the HA device if the sw version does not match
        if device and self._software_status.software_version != device.sw_version:

            device_registry.async_update_device(
                device_id=device.id,
                sw_version=self._software_status.software_version,
            )

        _LOGGER.info(
            "Connected to: %s %s running SW %s",
            self._model,
            self._unique_id,
            self._software_status.software_version,
        )

        # Get the device friendly name
        beolink_self = self._client.get_beolink_self(async_req=True).get()
        self._friendly_name = beolink_self.friendly_name

        # If the device has been updated with new sources, then the API will fail here.
        try:
            # Get all available sources.
            sources = self._client.get_available_sources(
                target_remote=False, async_req=True
            ).get()

        # Use a fallback list of sources
        except ValueError:
            _LOGGER.warning(
                "The API is outdated compared to the device software version. Using fallback sources"
            )
            sources = FALLBACK_SOURCES

        # Save all of the relevant enabled sources, both the ID and the friendly name for displaying.
        for source in sources.items:
            if source.is_enabled is True and source.id not in HIDDEN_SOURCE_IDS:
                self._source_list.append(source.id)
                self._source_list_friendly.append(source.name)

        # Set the default and maximum volume of the product.
        self._client.set_volume_settings(
            volume_settings=VolumeSettings(
                default=VolumeLevel(level=self._default_volume),
                maximum=VolumeLevel(level=self._max_volume),
            ),
            async_req=True,
        )

        # Get overall device state once. This is handled by WebSocket events the rest of the time.
        product_state = self._client.get_product_state(async_req=True).get()

        # Get volume information.
        self._volume = product_state.volume

        # Get all playback information.
        # Ensure that the metadata is not None upon startup
        if product_state.playback.metadata is not None:
            self._playback_metadata = product_state.playback.metadata

        self._playback_progress = product_state.playback.progress
        self._source_change = product_state.playback.source
        self._playback_state = product_state.playback.state

        self._last_update = utcnow()

        # Get the highest resolution available of the given images.
        self._update_artwork()

        # Get playback queue settings
        self._queue_settings = self._client.get_settings_queue(async_req=True).get()

        # Update beolink listener / leader attributes.
        await self._update_beolink()

        # Get paired remotes and bluetooth devices
        await self._update_bluetooth()

        # Set the static entity attributes that needed more information.
        self._attr_source_list = self._source_list_friendly

        # Wait for other entities to be initialized before starting the WebSocket listener
        await asyncio.sleep(1)

        # Only receive WebSocket notifications when the dispatchers are ready.
        await self.hass.data[DOMAIN][self.entry.unique_id][
            HASS_CONTROLLER
        ].start_notification_listener()

        return True

    def _get_beolink_jid(self, entity_id: str) -> str | None:
        """Get beolink JID from entity_id."""
        entity_registry = er.async_get(self.hass)

        # Make mypy happy
        entity_entry = cast(RegistryEntry, entity_registry.async_get(entity_id))
        config_entry = cast(
            ConfigEntry,
            self.hass.config_entries.async_get_entry(
                cast(str, entity_entry.config_entry_id)
            ),
        )

        try:
            jid = cast(str, config_entry.data[CONF_BEOLINK_JID])
        except KeyError:
            jid = None

        return jid

    def _get_entity_id_from_jid(self, jid: str) -> str | None:
        """Get entity_id from Beolink JID (if available)."""

        unique_id = jid.split(".")[2].split("@")[0]

        entity_registry = er.async_get(self.hass)
        entity_id = entity_registry.async_get_entity_id(
            Platform.MEDIA_PLAYER, DOMAIN, unique_id
        )

        return entity_id

    def _update_artwork(self) -> None:
        """Find the highest resolution image."""
        # Ensure that the metadata doesn't change mid processing.
        metadata = self._playback_metadata

        # Check if the metadata is not null and that there is art.
        if (
            isinstance(metadata, PlaybackContentMetadata)
            and isinstance(metadata.art, list)
            and len(metadata.art) > 0
        ):
            images = []
            # Images either have a key for specifying resolution or a "size" for the image.
            for image in metadata.art:
                # Netradio.
                if metadata.art[0].key is not None:
                    images.append(int(image.key.split("x")[0]))
                # Everything else.
                elif metadata.art[0].size is not None:
                    images.append(ArtSizeEnum[image.size].value)

            # Choose the largest image.
            self._media_image = metadata.art[images.index(max(images))]

        # Don't leave stale image metadata if there is no available artwork.
        else:
            self._media_image = Art()

    async def _update_beolink(self) -> None:
        """Update the current Beolink leader or Beolink listeners."""

        self._beolink_attribute = {}

        # Add Beolink JID
        self._beolink_attribute = {
            "beolink": {"self": {self._friendly_name: self._beolink_jid}}
        }

        peers = self._client.get_beolink_peers(async_req=True).get()

        if len(peers) > 0:
            self._beolink_attribute["beolink"]["peers"] = {}
            for peer in peers:
                self._beolink_attribute["beolink"]["peers"][
                    peer.friendly_name
                ] = peer.jid

        self._remote_leader = self._playback_metadata.remote_leader

        # Temp fix for mismatch in WebSocket metadata and "real" REST endpoint where the remote leader is not deleted.
        if self.source in (
            SourceEnum.lineIn,
            SourceEnum.uriStreamer,
        ):
            self._remote_leader = None

        # Create group members list
        group_members = []

        # If the device is a listener.
        if self._remote_leader is not None:
            group_members.append(
                cast(str, self._get_entity_id_from_jid(self._remote_leader.jid))
            )

            self._beolink_attribute["beolink"]["leader"] = {
                self._remote_leader.friendly_name: self._remote_leader.jid,
            }

        # If not listener, check if leader.
        else:
            self._beolink_listeners = self._client.get_beolink_listeners(
                async_req=True
            ).get()

            group_members.append(
                cast(str, self._get_entity_id_from_jid(self._beolink_jid))
            )

            # Check if the device is a leader.
            if len(self._beolink_listeners) > 0:
                # Get the friendly names from listeners from the peers
                beolink_listeners = {}
                for beolink_listener in self._beolink_listeners:
                    group_members.append(
                        cast(str, self._get_entity_id_from_jid(beolink_listener.jid))
                    )
                    for peer in peers:
                        if peer.jid == beolink_listener.jid:
                            beolink_listeners[peer.friendly_name] = beolink_listener.jid
                            break

                self._beolink_attribute["beolink"]["listeners"] = beolink_listeners

        self._attr_group_members = group_members

    @callback
    def _update_coordinator_data(self) -> None:
        """Update data from coordinator."""
        self._queue_settings = self.coordinator.data["queue_settings"]

        self.async_write_ha_state()

    async def _update_bluetooth(self) -> None:
        """Update the current bluetooth devices that are connected and paired remotes."""

        self._bluetooth_attribute = {"bluetooth": {}}

        # Add paired remotes
        bluetooth_remote_list = self._client.get_bluetooth_remotes(async_req=True).get()

        if len(bluetooth_remote_list.items) > 0:
            self._bluetooth_attribute["bluetooth"]["remote"] = {}

            for remote in bluetooth_remote_list.items:
                self._bluetooth_attribute["bluetooth"]["remote"][
                    remote.name
                ] = remote.address

        # Add currently connected bluetooth device
        bluetooth_device_list = self._client.get_bluetooth_devices_status(
            async_req=True
        ).get()

        for bluetooth_device in bluetooth_device_list.items:
            if bluetooth_device.connected:
                self._bluetooth_attribute["bluetooth"]["device"] = {
                    bluetooth_device.name: bluetooth_device.address
                }

        if not self._bluetooth_attribute["bluetooth"]:
            self._bluetooth_attribute = None

    async def _update_connection_state(self, connection_state: bool) -> None:
        """Update entity connection state."""
        self._attr_available = connection_state

        self.async_write_ha_state()

    async def _update_playback_metadata(self, data: PlaybackContentMetadata) -> None:
        """Update _playback_metadata and related."""
        self._playback_metadata = data

        # Update current artwork and remote leader.
        self._update_artwork()
        await self._update_beolink()

        self.async_write_ha_state()

    async def _update_playback_error(self, data: PlaybackError) -> None:
        """Show playback error."""
        _LOGGER.error(data.error)

    async def _update_playback_progress(self, data: PlaybackProgress) -> None:
        """Update _playback_progress and last update."""
        self._playback_progress = data
        self._last_update = utcnow()

        self.async_write_ha_state()

    async def _update_playback_state(self, data: RenderingState) -> None:
        """Update _playback_state and related."""
        self._playback_state = data

        # Update entity state based on the playback state.
        self._state = self._playback_state.value

        self.async_write_ha_state()

    async def _update_source_change(self, data: Source) -> None:
        """Update _source_change and related."""
        self._source_change = data

        # Update bluetooth device attribute.
        if self.source == SourceEnum.bluetooth:
            await self._update_bluetooth()

        self.async_write_ha_state()

    async def _update_notification(self, data: WebsocketNotificationTag) -> None:
        """Update _notification and Misc. updates."""
        self._notification = data

        # Update beolink
        if self._notification.value in (
            "beolinkAvailableListeners",
            "beolinkListeners",
            "configuration",
        ):
            # Update the device friendly name
            if self._notification.value == "configuration":
                beolink_self = self._client.get_beolink_self(async_req=True).get()
                self._friendly_name = beolink_self.friendly_name

            await self._update_beolink()

        # Update bluetooth devices
        elif self._notification.value == "bluetoothDevices":
            await self._update_bluetooth()

        # Update remote control devices
        elif self._notification.value == "remoteControlDevices":
            # Notify the WebSocket listener that a remote is available
            async_dispatcher_send(
                self.hass,
                f"{self._unique_id}_{WS_REMOTE_CONTROL_AVAILABLE}",
            )
            await self._update_bluetooth()

        self.async_write_ha_state()

    async def _update_volume(self, data: VolumeState) -> None:
        """Update _volume."""
        self._volume = data

        self.async_write_ha_state()

    @property
    def state(self) -> MediaPlayerState:
        """Return the current state of the media player."""
        return cast(MediaPlayerState, StateEnum[self._state])

    @property
    def volume_level(self) -> float:
        """Volume level of the media player (0..1)."""
        return float(self._volume.level.level / 100)

    @property
    def is_volume_muted(self) -> bool:
        """Boolean if volume is currently muted."""
        return cast(bool, self._volume.muted.muted)

    @property
    def media_content_type(self) -> str:
        """Return the current media type."""
        # Hard to determine content type
        if self.source == SourceEnum.uriStreamer:
            return MediaType.URL
        return MediaType.MUSIC

    @property
    def media_duration(self) -> int | None:
        """Return the total duration of the current track in seconds."""
        if self._playback_metadata.total_duration_seconds not in NO_METADATA:
            return cast(int, self._playback_metadata.total_duration_seconds)
        return None

    @property
    def media_position(self) -> int | None:
        """Return the current playback progress."""
        # Don't show progress if the the device is a Beolink listener.
        if self._remote_leader is None:
            return cast(int, self._playback_progress.progress)
        return None

    @property
    def media_position_updated_at(self) -> datetime:
        """Return the last time that the playback position was updated."""
        return self._last_update

    @property
    def media_image_url(self) -> str | None:
        """Return URL of the currently playing music."""
        if isinstance(self._media_image.url, (str, type(None))):
            return self._media_image.url
        return None

    @property
    def media_image_remotely_accessible(self) -> bool:
        """Return whether or not the image of the current media is available outside the local network."""
        return not self._media_image.has_local_image

    @property
    def media_title(self) -> str | None:
        """Return the currently playing title."""
        if self._playback_metadata.title not in NO_METADATA:
            return cast(str, self._playback_metadata.title)
        return None

    @property
    def media_album_name(self) -> str | None:
        """Return the currently playing album name."""
        if self._playback_metadata.album_name not in NO_METADATA:
            return cast(str, self._playback_metadata.album_name)
        return None

    @property
    def media_album_artist(self) -> str | None:
        """Return the currently playing artist name."""
        if self._playback_metadata.artist_name not in NO_METADATA:
            return cast(str, self._playback_metadata.artist_name)
        return None

    @property
    def media_track(self) -> int | None:
        """Return the currently playing track."""
        if self._playback_metadata.track not in NO_METADATA:
            return cast(int, self._playback_metadata.track)
        return None

    @property
    def media_channel(self) -> str | None:
        """Return the currently playing channel."""
        if self._playback_metadata.organization not in NO_METADATA:
            return cast(str, self._playback_metadata.organization)
        return None

    @property
    def source(self) -> str | None:
        """Return the current audio source."""

        # Try to fix some of the source_change chromecast weirdness.
        if hasattr(self._playback_metadata, "title"):

            # source_change is chromecast but line in is selected.
            if self._playback_metadata.title == SourceEnum.lineIn:
                return SourceEnum.lineIn

            # source_change is chromecast but bluetooth is selected.
            if self._playback_metadata.title == SourceEnum.bluetooth:
                return SourceEnum.bluetooth

            # source_change is line in, bluetooth or optical but stale metadata is sent through the WebSocket,
            # And the source has not changed.
            if self._source_change.id in (
                SourceEnum.bluetooth,
                SourceEnum.lineIn,
                SourceEnum.spdif,
            ):
                return SourceEnum.chromeCast

        # source_change is chromecast and there is metadata but no artwork. Bluetooth does support metadata but not artwork
        # So i assume that it is bluetooth and not chromecast
        if (
            hasattr(self._playback_metadata, "art")
            and self._playback_metadata.art is not None
        ):
            if (
                len(self._playback_metadata.art) == 0
                and self._playback_source.name == SourceEnum.bluetooth
            ):
                return SourceEnum.bluetooth

        return cast(str, self._source_change.name)

    @property
    def device_info(self) -> DeviceInfo:
        """Return information about the device."""
        return DeviceInfo(
            configuration_url=f"http://{self._host}/#/",
            identifiers={(DOMAIN, self._unique_id)},
            manufacturer="Bang & Olufsen",
            model=self._model,
            name=self.name,
            sw_version=self._software_status.software_version,
        )

    @property
    def shuffle(self) -> bool | None:
        """Return if queues should be shuffled."""
        return cast(bool, self._queue_settings.shuffle)

    @property
    def repeat(self) -> RepeatMode | None:
        """Return current repeat setting for queues."""
        return cast(RepeatMode, RepeatEnum(self._queue_settings.repeat).name)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return information that is not returned anywhere else."""
        attributes: dict[str, Any] = {}

        if self._beolink_attribute is not None:
            attributes.update(self._beolink_attribute)

        if self._bluetooth_attribute is not None:
            attributes.update(self._bluetooth_attribute)

        if attributes:
            return attributes

        return None

    async def async_volume_up(self) -> None:
        """Volume up the on media player."""
        new_volume = min(self._volume.level.level + self._volume_step, self._max_volume)
        self._client.set_current_volume_level(
            volume_level=VolumeLevel(level=new_volume),
            async_req=True,
        )

    async def async_volume_down(self) -> None:
        """Volume down the on media player."""
        new_volume = max(self._volume.level.level - self._volume_step, 0)
        self._client.set_current_volume_level(
            volume_level=VolumeLevel(level=new_volume),
            async_req=True,
        )

    async def async_set_volume_level(self, volume: float) -> None:
        """Set volume level, range 0..1."""
        self._client.set_current_volume_level(
            volume_level=VolumeLevel(level=int(volume * 100)),
            async_req=True,
        )

    async def async_mute_volume(self, mute: bool) -> None:
        """Mute or unmute media player."""
        self._client.set_volume_mute(
            volume_mute=VolumeMute(muted=mute),
            async_req=True,
        )

    async def async_media_play_pause(self) -> None:
        """Toggle play/pause media player."""
        if self.state == MediaPlayerState.PLAYING:
            await self.async_media_pause()
        elif self.state in (MediaPlayerState.PAUSED, MediaPlayerState.IDLE):
            await self.async_media_play()

    async def async_media_pause(self) -> None:
        """Pause media player."""
        self._client.post_playback_command(command="pause", async_req=True)

    async def async_media_play(self) -> None:
        """Play media player."""
        self._client.post_playback_command(command="play", async_req=True)

    async def async_media_stop(self) -> None:
        """Pause media player."""
        self._client.post_playback_command(command="stop", async_req=True)

    async def async_media_next_track(self) -> None:
        """Send the next track command."""
        self._client.post_playback_command(command="skip", async_req=True)

    async def async_media_seek(self, position: float) -> None:
        """Seek to position in ms."""
        if self.source == SourceEnum.deezer:
            self._client.seek_to_position(
                position_ms=int(position * 1000), async_req=True
            )
            # Try to prevent the playback progress from bouncing in the UI.
            self._last_update = utcnow()
            self._playback_progress = PlaybackProgress(progress=int(position))

            self.async_write_ha_state()
        else:
            _LOGGER.error("Seeking is currently only supported when using Deezer")

    async def async_media_previous_track(self) -> None:
        """Send the previous track command."""
        self._client.post_playback_command(command="prev", async_req=True)

    async def async_clear_playlist(self) -> None:
        """Clear the current playback queue."""
        self._client.post_clear_queue(async_req=True)

    async def async_set_shuffle(self, shuffle: bool) -> None:
        """Set playback queues to shuffle."""
        self._client.set_settings_queue(
            play_queue_settings=PlayQueueSettings(shuffle=shuffle),
            async_req=True,
        )

        self._queue_settings.shuffle = shuffle

    async def async_set_repeat(self, repeat: RepeatMode) -> None:
        """Set playback queues to repeat."""
        self._client.set_settings_queue(
            play_queue_settings=PlayQueueSettings(repeat=RepeatEnum[repeat]),
            async_req=True,
        )
        self._queue_settings.repeat = RepeatEnum[repeat]

    async def async_select_source(self, source: str) -> None:
        """Select an input source."""
        if source in self._source_list_friendly:
            index = self._source_list_friendly.index(source)

            self._client.set_active_source(
                source_id=self._source_list[index],
                async_req=True,
            )

        else:
            _LOGGER.error(
                "Invalid source: %s. Valid sources are: %s",
                source,
                self._source_list_friendly,
            )

    async def async_join_players(self, group_members: list[str]) -> None:
        """Create a Beolink session with defined group members."""

        # Use the touch to join if no entities have been defined
        if len(group_members) == 0:
            await self.async_beolink_join()
            return

        jids = []
        # Get JID for each group member
        for group_member in group_members:

            jid = self._get_beolink_jid(group_member)

            # Invalid entity
            if jid is None:
                _LOGGER.warning("Error adding %s to group", group_member)
                continue

            jids.append(jid)

        await self.async_beolink_expand(jids)

    async def async_unjoin_player(self) -> None:
        """Unexpand device from Beolink session."""
        await self.async_beolink_leave()

    async def async_play_media(
        self,
        media_type: MediaType | str,
        media_id: str,
        **kwargs: Any,
    ) -> None:
        """Play from: netradio station id, URI, favourite or Deezer."""

        if media_source.is_media_source_id(media_id):
            media_type = MediaType.URL

            sourced_media = await media_source.async_resolve_media(
                self.hass, media_id, self.entity_id
            )

            media_id = async_process_play_media_url(self.hass, sourced_media.url)
            # Remove playlist extension as it is unsupported.
            # A better way may be to open the m3u file and get the stream URI from there(?)
            if media_id.endswith(".m3u"):
                media_id = media_id.replace(".m3u", "")

        if media_type not in VALID_MEDIA_TYPES:
            _LOGGER.error(
                "%s is an invalid type. Valid values are: %s",
                media_type,
                VALID_MEDIA_TYPES,
            )
            return

        if media_type == MediaType.URL:

            self._client.post_uri_source(uri=Uri(location=media_id), async_req=True)

        elif media_type == BangOlufsenMediaType.FAVOURITE:
            self._client.activate_preset(id=media_id, async_req=True)

        elif media_type == BangOlufsenMediaType.DEEZER:
            try:
                if media_id == "flow":

                    deezer_id = None

                    if "id" in kwargs[ATTR_MEDIA_EXTRA]:
                        deezer_id = kwargs[ATTR_MEDIA_EXTRA]["id"]

                    # Play Deezer flow.
                    self._client.start_deezer_flow(
                        user_flow=UserFlow(user_id=deezer_id), async_req=True
                    )

                else:
                    # Play a Deezer playlist or album.
                    if any(match in media_id for match in ("playlist", "album")):

                        start_from = 0
                        if "start_from" in kwargs[ATTR_MEDIA_EXTRA]:
                            start_from = kwargs[ATTR_MEDIA_EXTRA]["start_from"]

                        self._client.add_to_queue(
                            play_queue_item=PlayQueueItem(
                                provider=PlayQueueItemType(value="deezer"),
                                start_now_from_position=start_from,
                                type="playlist",
                                uri=media_id,
                            ),
                            async_req=True,
                        )

                    # Play a Deezer track.
                    else:
                        self._client.add_to_queue(
                            play_queue_item=PlayQueueItem(
                                provider=PlayQueueItemType(value="deezer"),
                                start_now_from_position=0,
                                type="track",
                                uri=media_id,
                            ),
                            async_req=True,
                        )

            except ApiException as error:
                _LOGGER.error(json.loads(error.body)["message"])

    async def async_browse_media(
        self,
        media_content_type: str | None = None,
        media_content_id: str | None = None,
    ) -> BrowseMedia:
        """Implement the WebSocket media browsing helper."""
        return await media_source.async_browse_media(
            self.hass,
            media_content_id,
            content_filter=lambda item: item.media_content_type.startswith("audio/"),
        )

    # Custom services:
    async def async_beolink_join(self, beolink_jid: str | None = None) -> None:
        """Join a Beolink multi-room experience."""
        if beolink_jid is None:
            self._client.join_latest_beolink_experience(async_req=True)
        else:
            if not check_valid_jid(beolink_jid):
                return

            self._client.join_beolink_peer(jid=beolink_jid, async_req=True)

    async def async_beolink_expand(self, beolink_jids: list[str]) -> None:
        """Expand a Beolink multi-room experience with a device or devices."""
        # Check if the Beolink JIDs are valid.
        for beolink_jid in beolink_jids:
            if not check_valid_jid(beolink_jid):
                _LOGGER.error("Invalid Beolink JID: %s", beolink_jid)
                return

        self.hass.async_create_task(self._beolink_expand(beolink_jids))

    async def _beolink_expand(self, beolink_jids: list[str]) -> None:
        """Expand the Beolink experience with a non blocking delay."""
        for beolink_jid in beolink_jids:
            self._client.post_beolink_expand(jid=beolink_jid, async_req=True)
            await asyncio.sleep(1)

    async def async_beolink_unexpand(self, beolink_jids: list[str]) -> None:
        """Unexpand a Beolink multi-room experience with a device or devices."""
        # Check if the Beolink JIDs are valid.
        for beolink_jid in beolink_jids:
            if not check_valid_jid(beolink_jid):
                return

        self.hass.async_create_task(self._beolink_unexpand(beolink_jids))

    async def _beolink_unexpand(self, beolink_jids: list[str]) -> None:
        """Unexpand the Beolink experience with a non blocking delay."""
        for beolink_jid in beolink_jids:
            self._client.post_beolink_unexpand(jid=beolink_jid, async_req=True)
            await asyncio.sleep(1)

    async def async_beolink_leave(self) -> None:
        """Leave the current Beolink experience."""
        self._client.post_beolink_leave(async_req=True)

    async def async_beolink_allstandby(self) -> None:
        """Set all connected Beolink devices to standby."""
        self._client.post_beolink_allstandby(async_req=True)

    async def async_beolink_listener_command(
        self, command: str, parameter: str | None = None
    ) -> None:
        """Receive a command from the Beolink leader."""
        for command_list in ACCEPTED_COMMANDS_LISTS:
            if command in command_list:
                # Get the parameter type.
                parameter_type = command_list[-1]

                # Run the command.
                if parameter is not None:
                    await getattr(self, f"async_{command}")(parameter_type(parameter))

                elif parameter_type is None:
                    await getattr(self, f"async_{command}")()

    async def async_beolink_leader_command(
        self, command: str, parameter: str | None = None
    ) -> None:
        """Send a command to the Beolink leader."""
        for command_list in ACCEPTED_COMMANDS_LISTS:
            if command in command_list:

                # Get the parameter type.
                parameter_type = command_list[-1]

                # Check for valid parameter type.
                if parameter_type is not None:
                    try:
                        parameter = parameter_type(parameter)
                    except (ValueError, TypeError):
                        _LOGGER.error("Invalid parameter")
                        return

                elif parameter_type is None and parameter is not None:
                    _LOGGER.error("Invalid parameter")
                    return

                # Forward the command to the leader if a listener.
                if self._remote_leader is not None:
                    async_dispatcher_send(
                        self.hass,
                        f"{self._remote_leader.jid}_{BEOLINK_LEADER_COMMAND}",
                        command,
                        parameter,
                    )

                # Run the command if leader.
                else:
                    if parameter is not None:
                        await getattr(self, f"async_{command}")(
                            parameter_type(parameter)
                        )

                    elif parameter_type is None:
                        await getattr(self, f"async_{command}")()

    async def async_beolink_set_volume(self, volume_level: str) -> None:
        """Set volume level for all connected Beolink devices."""

        # Get the remote leader to send the volume command to listeners
        if self._remote_leader is not None:
            async_dispatcher_send(
                self.hass,
                f"{self._remote_leader.jid}_{BEOLINK_VOLUME}",
                volume_level,
            )

        else:
            await self.async_set_volume_level(volume=float(volume_level))

            for beolink_listener in self._beolink_listeners:
                async_dispatcher_send(
                    self.hass,
                    f"{beolink_listener.jid}_{BEOLINK_LISTENER_COMMAND}",
                    "set_volume_level",
                    volume_level,
                )

    async def async_overlay_audio(
        self,
        uri: str | None = None,
        absolute_volume: int | None = None,
        volume_offset: int | None = None,
        tts: str | None = None,
        tts_language: str | None = None,
    ) -> None:
        """Overlay audio over any currently playing audio."""

        if absolute_volume and volume_offset:
            _LOGGER.error(
                "Can't define absolute volume and volume offset at the same time"
            )
            return

        if tts and uri:
            _LOGGER.error("Can't define URI and TTS message at the same time")
            return

        volume = None

        if absolute_volume:
            volume = absolute_volume
        elif volume_offset:
            # Ensure that the volume is not above 100
            volume = min(self._volume.level.level + volume_offset, 100)

        if uri:
            media_id = uri

            # Play local HA file.
            if media_source.is_media_source_id(media_id):
                sourced_media = await media_source.async_resolve_media(
                    self.hass, media_id, self.entity_id
                )

                media_id = async_process_play_media_url(self.hass, sourced_media.url)

            self._client.post_overlay_play(
                overlay_play_request=OverlayPlayRequest(
                    uri=Uri(location=media_id), volume_absolute=volume
                ),
                async_req=True,
            )

        elif tts:
            self._client.post_overlay_play(
                overlay_play_request=OverlayPlayRequest(
                    text_to_speech=OverlayPlayRequestTextToSpeechTextToSpeech(
                        lang=tts_language, text=tts
                    ),
                    volume_absolute=volume,
                ),
                async_req=True,
            )
