"""Config flow for the Bang & Olufsen integration."""
from __future__ import annotations

import ipaddress
import logging
from typing import Any, TypedDict

from aiohttp.client_exceptions import ClientConnectorError
from mozart_api.exceptions import ApiException
from mozart_api.mozart_client import MozartClient
import voluptuous as vol

from homeassistant.components.zeroconf import ZeroconfServiceInfo
from homeassistant.config_entries import ConfigEntry, ConfigFlow, OptionsFlow
from homeassistant.const import CONF_HOST, CONF_MODEL
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    SelectSelector,
    SelectSelectorConfig,
)

from .const import (
    ATTR_FRIENDLY_NAME,
    ATTR_ITEM_NUMBER,
    ATTR_SERIAL_NUMBER,
    ATTR_TYPE_NUMBER,
    COMPATIBLE_MODELS,
    CONF_BEOLINK_JID,
    CONF_DEFAULT_VOLUME,
    CONF_MAX_VOLUME,
    CONF_SERIAL_NUMBER,
    DEFAULT_DEFAULT_VOLUME,
    DEFAULT_MAX_VOLUME,
    DEFAULT_MODEL,
    DEFAULT_VOLUME_RANGE,
    DOMAIN,
    MAX_VOLUME_RANGE,
)


def _config_schema(
    default_volume: int = DEFAULT_DEFAULT_VOLUME,
    max_volume: int = DEFAULT_MAX_VOLUME,
) -> dict:
    """Create a schema for configuring the device with adjustable default values."""
    return {
        vol.Required(CONF_DEFAULT_VOLUME, default=default_volume): vol.All(
            NumberSelector(
                NumberSelectorConfig(
                    step=1,
                    min=DEFAULT_VOLUME_RANGE.start,
                    max=DEFAULT_VOLUME_RANGE.stop,
                )
            ),
            vol.Coerce(int),
        ),
        vol.Required(CONF_MAX_VOLUME, default=max_volume): vol.All(
            NumberSelector(
                NumberSelectorConfig(
                    step=1,
                    min=MAX_VOLUME_RANGE.start,
                    max=MAX_VOLUME_RANGE.stop,
                )
            ),
            vol.Coerce(int),
        ),
    }


class UserInput(TypedDict, total=False):
    """TypedDict for user_input."""

    default_volume: int
    host: str
    jid: str
    max_volume: int
    model: str
    name: str


class BangOlufsenConfigFlowHandler(ConfigFlow, domain=DOMAIN):
    """Handle a config flow."""

    _beolink_jid = ""
    _client: MozartClient
    _host = ""
    _model = ""
    _name = ""
    _serial_number = ""

    def __init__(self) -> None:
        """Init the config flow."""

    VERSION = 1

    async def _compile_data(self) -> UserInput:
        """Compile data for entry creation."""
        # Get current volume settings and if the device has a battery
        async with self._client:
            volume_settings = await self._client.get_volume_settings()

        # Create a dict containing all necessary information for setup
        data = UserInput()

        data[CONF_DEFAULT_VOLUME] = (
            volume_settings.default.level
            if volume_settings.default and volume_settings.default.level
            else DEFAULT_DEFAULT_VOLUME
        )
        data[CONF_HOST] = self._host
        data[CONF_BEOLINK_JID] = self._beolink_jid
        data[CONF_MAX_VOLUME] = (
            volume_settings.maximum.level
            if volume_settings.maximum and volume_settings.maximum.level
            else DEFAULT_MAX_VOLUME
        )
        data[CONF_MODEL] = self._model

        return data

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        if user_input is not None:
            self._host = user_input[CONF_HOST]
            self._model = user_input[CONF_MODEL]

            # Check if the IP address is a valid address.
            try:
                ipaddress.ip_address(self._host)
            except ValueError:
                return self.async_abort(reason="value_error")

            self._client = MozartClient(self._host, urllib3_logging_level=logging.ERROR)

            # Try to get information from Beolink self method.
            async with self._client:
                try:
                    beolink_self = await self._client.get_beolink_self(
                        _request_timeout=3
                    )

                except (ApiException, ClientConnectorError, TimeoutError) as error:
                    return self.async_abort(
                        reason={
                            ApiException: "api_exception",
                            ClientConnectorError: "client_connector_error",
                            TimeoutError: "timeout_error",
                        }[type(error)]
                    )

            self._beolink_jid = beolink_self.jid
            self._serial_number = beolink_self.jid.split(".")[2].split("@")[0]

            await self.async_set_unique_id(self._serial_number)
            self._abort_if_unique_id_configured()

            return await self.async_step_confirm()

        data_schema = {
            vol.Required(CONF_HOST): str,
            vol.Required(CONF_MODEL, default=DEFAULT_MODEL): SelectSelector(
                SelectSelectorConfig(options=COMPATIBLE_MODELS)
            ),
        }

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(data_schema),
        )

    async def async_step_zeroconf(
        self, discovery_info: ZeroconfServiceInfo
    ) -> FlowResult:
        """Handle discovery using Zeroconf."""

        # Check if the discovered device is a Mozart device
        if ATTR_FRIENDLY_NAME not in discovery_info.properties:
            return self.async_abort(reason="not_mozart_device")

        self._host = discovery_info.host
        self._model = discovery_info.hostname[:-16].replace("-", " ")
        self._serial_number = discovery_info.properties[ATTR_SERIAL_NUMBER]
        self._beolink_jid = f"{discovery_info.properties[ATTR_TYPE_NUMBER]}.{discovery_info.properties[ATTR_ITEM_NUMBER]}.{self._serial_number}@products.bang-olufsen.com"

        self.context["title_placeholders"] = {
            "name": discovery_info.properties[ATTR_FRIENDLY_NAME]
        }

        await self.async_set_unique_id(self._serial_number)
        self._abort_if_unique_id_configured(updates={CONF_HOST: self._host})

        self._client = MozartClient(self._host, urllib3_logging_level=logging.ERROR)

        return await self.async_step_confirm()

    async def async_step_confirm(
        self, user_input: UserInput | None = None
    ) -> FlowResult:
        """Confirm the configuration of the device."""
        if user_input is not None:
            data = await self._compile_data()
            return self.async_create_entry(title=self._name, data=data)

        # Ensure that created entities have a unique and easily identifiable id and not a "friendly name"
        self._name = f"{self._model}-{self._serial_number}"

        await self.async_set_unique_id(self._serial_number)
        self._abort_if_unique_id_configured()

        self._set_confirm_only()

        return self.async_show_form(
            step_id="confirm",
            description_placeholders={
                CONF_HOST: self._host,
                CONF_MODEL: self._model,
                CONF_SERIAL_NUMBER: self._serial_number,
            },
            last_step=True,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Get the options flow handler."""
        return BangOlufsenOptionsFlowHandler(config_entry)


class BangOlufsenOptionsFlowHandler(OptionsFlow):
    """Handle an options flow."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        """Initialize the options flow handler."""
        self._client = MozartClient(host=config_entry.data[CONF_HOST])
        self._config_entry = config_entry

    async def async_step_init(self, user_input: UserInput | None = None) -> FlowResult:
        """Manage the options menu."""
        if user_input is not None:
            # Make sure that everything get included in the data.
            data = user_input
            data[CONF_MODEL] = self._config_entry.data[CONF_MODEL]
            data[CONF_BEOLINK_JID] = self._config_entry.data[CONF_BEOLINK_JID]
            data[CONF_HOST] = self._config_entry.data[CONF_HOST]

            return self.async_create_entry(title=self._config_entry.title, data=data)

        # Create data schema with the current volume options, not necessarily the ones set in Home Assistant.
        # Also add the ability to change the friendly name in Home Assistant
        async with self._client:
            try:
                volume_settings = await self._client.get_volume_settings(
                    _request_timeout=3
                )

            except (ApiException, ClientConnectorError, TimeoutError) as error:
                return self.async_abort(
                    reason={
                        ApiException: "api_exception",
                        ClientConnectorError: "client_connector_error",
                        TimeoutError: "timeout_error",
                    }[type(error)]
                )

        data_schema = _config_schema(
            default_volume=volume_settings.default.level
            if volume_settings.default and volume_settings.default.level
            else DEFAULT_DEFAULT_VOLUME,
            max_volume=volume_settings.maximum.level
            if volume_settings.maximum and volume_settings.maximum.level
            else DEFAULT_MAX_VOLUME,
        )

        # Create options form with selected options.
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(data_schema),
            last_step=True,
        )
