"""Event entities for the Bang & Olufsen integration."""

from __future__ import annotations

import logging
from typing import cast

from mozart_api.models import PairedRemote
from mozart_api.mozart_client import MozartClient

from homeassistant.components.event import EventDeviceClass, EventEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_MODEL
from homeassistant.core import HomeAssistant, callback
import homeassistant.helpers.device_registry as dr
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import BangOlufsenData
from .const import (
    BEO_REMOTE_CONTROL_KEYS,
    BEO_REMOTE_KEY_EVENTS,
    BEO_REMOTE_KEYS,
    BEO_REMOTE_LIGHT_KEYS,
    BEO_REMOTE_SUBMENU_CONTROL,
    BEO_REMOTE_SUBMENU_LIGHT,
    CONNECTION_STATUS,
    DEVICE_BUTTON_EVENTS,
    DEVICE_BUTTONS,
    DOMAIN,
    PROXIMITY_EVENTS,
    BangOlufsenModelSupport,
    WebsocketNotification,
)
from .entity import BangOlufsenEntity
from .util import set_platform_initialized

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Sensor entities from config entry."""
    data: BangOlufsenData = hass.data[DOMAIN][config_entry.entry_id]

    # Add physical "buttons"
    entities: list[EventEntity] = [
        BangOlufsenButtonEvent(config_entry, data.client, button_type)
        for button_type in DEVICE_BUTTONS
    ]

    # Check if device supports proximity detection.
    if config_entry.data[CONF_MODEL] in BangOlufsenModelSupport.PROXIMITY_SENSOR.value:
        entities.append(BangOlufsenEventProximity(config_entry, data.client))

    # Get if a remote control is connected and the remote
    bluetooth_remote_list = await data.client.get_bluetooth_remotes()

    if bool(len(cast(list[PairedRemote], bluetooth_remote_list.items))):
        # Support only the first remote for now.
        remote: PairedRemote = cast(list[PairedRemote], bluetooth_remote_list.items)[0]
        assert remote.serial_number

        # Create Beoremote One device
        assert config_entry.unique_id
        device_registry = dr.async_get(hass)
        device_registry.async_get_or_create(
            config_entry_id=config_entry.entry_id,
            identifiers={(DOMAIN, remote.serial_number)},
            name=f"Beoremote One {remote.serial_number}",
            model="Beoremote One",
            serial_number=remote.serial_number,
            sw_version=remote.app_version,
            manufacturer="Bang & Olufsen",
            via_device=(DOMAIN, config_entry.unique_id),
        )

        # Add Light keys
        entities.extend(
            [
                BangOlufsenRemoteKeyEvent(
                    config_entry,
                    data.client,
                    remote,
                    f"{BEO_REMOTE_SUBMENU_LIGHT}/{key_type}",
                )
                for key_type in (*BEO_REMOTE_KEYS, *BEO_REMOTE_LIGHT_KEYS)
            ]
        )

        # Add Control keys
        entities.extend(
            [
                BangOlufsenRemoteKeyEvent(
                    config_entry,
                    data.client,
                    remote,
                    f"{BEO_REMOTE_SUBMENU_CONTROL}/{key_type}",
                )
                for key_type in (*BEO_REMOTE_KEYS, *BEO_REMOTE_CONTROL_KEYS)
            ]
        )

    async_add_entities(new_entities=entities)

    set_platform_initialized(data)


class BangOlufsenButtonEvent(BangOlufsenEntity, EventEntity):
    """Event class for Button events."""

    _attr_device_class = EventDeviceClass.BUTTON
    _attr_event_types = DEVICE_BUTTON_EVENTS
    _attr_icon = "mdi:gesture-tap-button"

    def __init__(
        self, entry: ConfigEntry, client: MozartClient, button_type: str
    ) -> None:
        """Initialize Button."""
        super().__init__(entry, client)

        self._attr_unique_id = f"{self._unique_id}_{button_type}"

        # Make the native button name Home Assistant compatible
        self._attr_translation_key = button_type.lower()

        self._button_type = button_type

    @callback
    def _async_handle_event(self, event: str) -> None:
        """Handle Beoremote One key event."""
        self._trigger_event(event)
        self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        """Listen to WebSocket button events."""
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                f"{self._unique_id}_{CONNECTION_STATUS}",
                self._async_update_connection_state,
            )
        )
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                f"{self._unique_id}_{WebsocketNotification.BUTTON}_{self._button_type}",
                self._async_handle_event,
            )
        )


class BangOlufsenRemoteKeyEvent(BangOlufsenEntity, EventEntity):
    """Event class for Beoremote One key events."""

    _attr_device_class = EventDeviceClass.BUTTON
    _attr_event_types = BEO_REMOTE_KEY_EVENTS
    _attr_icon = "mdi:remote"

    def __init__(
        self,
        entry: ConfigEntry,
        client: MozartClient,
        remote: PairedRemote,
        key_type: str,
    ) -> None:
        """Initialize Beoremote One key."""
        super().__init__(entry, client)
        assert remote.serial_number

        self._attr_unique_id = f"{remote.serial_number}_{key_type}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, remote.serial_number)}
        )
        # Make the native key name Home Assistant compatible
        self._attr_translation_key = key_type.lower().replace("/", "_")

        self._key_type = key_type

    @callback
    def _async_handle_event(self, event: str) -> None:
        """Handle Beoremote One key event."""
        self._trigger_event(event)
        self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        """Listen to WebSocket Beoremote One key events."""
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                f"{self._unique_id}_{CONNECTION_STATUS}",
                self._async_update_connection_state,
            )
        )
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                f"{self._unique_id}_{WebsocketNotification.BEO_REMOTE_BUTTON}_{self._key_type}",
                self._async_handle_event,
            )
        )


class BangOlufsenEventProximity(BangOlufsenEntity, EventEntity):
    """Event class for proximity sensor events."""

    _attr_icon = "mdi:account-question"
    _attr_translation_key = "proximity"
    _attr_event_types = PROXIMITY_EVENTS
    _attr_device_class = EventDeviceClass.MOTION

    def __init__(self, entry: ConfigEntry, client: MozartClient) -> None:
        """Init the proximity event."""
        super().__init__(entry, client)

        self._attr_unique_id = f"{self._unique_id}_proximity"

    @callback
    def _async_handle_event(self, event: str) -> None:
        """Handle Beoremote One key event."""
        self._trigger_event(event)
        self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        """Turn on the dispatchers."""
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                f"{self._unique_id}_{CONNECTION_STATUS}",
                self._async_update_connection_state,
            )
        )
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                f"{self._unique_id}_{WebsocketNotification.PROXIMITY}",
                self._async_handle_event,
            )
        )
