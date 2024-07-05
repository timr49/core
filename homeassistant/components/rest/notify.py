"""RESTful platform for notify component."""

from __future__ import annotations

from http import HTTPStatus
import logging
from typing import Any

import httpx
import voluptuous as vol

from homeassistant.components.notify import (
    ATTR_MESSAGE,
    ATTR_TARGET,
    ATTR_TITLE,
    ATTR_TITLE_DEFAULT,
    PLATFORM_SCHEMA as NOTIFY_PLATFORM_SCHEMA,
    BaseNotificationService,
)
from homeassistant.const import (
    CONF_AUTHENTICATION,
    CONF_HEADERS,
    CONF_METHOD,
    CONF_NAME,
    CONF_PARAMS,
    CONF_PASSWORD,
    CONF_RESOURCE,
    CONF_USERNAME,
    CONF_VERIFY_SSL,
    HTTP_BASIC_AUTHENTICATION,
    HTTP_DIGEST_AUTHENTICATION,
)
from homeassistant.core import HomeAssistant
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.httpx_client import get_async_client
from homeassistant.helpers.template import Template
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType

CONF_DATA = "data"
CONF_DATA_TEMPLATE = "data_template"
CONF_DATA_TYPES = "data_types"
CONF_MESSAGE_PARAMETER_NAME = "message_param_name"
CONF_TARGET_PARAMETER_NAME = "target_param_name"
CONF_TITLE_PARAMETER_NAME = "title_param_name"
DEFAULT_MESSAGE_PARAM_NAME = "message"
DEFAULT_METHOD = "GET"
DEFAULT_VERIFY_SSL = True

PLATFORM_SCHEMA = NOTIFY_PLATFORM_SCHEMA.extend(
    {
        vol.Required(CONF_RESOURCE): cv.url,
        vol.Optional(
            CONF_MESSAGE_PARAMETER_NAME, default=DEFAULT_MESSAGE_PARAM_NAME
        ): cv.string,
        vol.Optional(CONF_METHOD, default=DEFAULT_METHOD): vol.In(
            ["POST", "GET", "POST_JSON"]
        ),
        vol.Optional(CONF_HEADERS): vol.Schema({cv.string: cv.string}),
        vol.Optional(CONF_PARAMS): vol.Schema({cv.string: cv.string}),
        vol.Optional(CONF_NAME): cv.string,
        vol.Optional(CONF_TARGET_PARAMETER_NAME): cv.string,
        vol.Optional(CONF_TITLE_PARAMETER_NAME): cv.string,
        vol.Optional(CONF_DATA): vol.All(dict, cv.template_complex),
        vol.Optional(CONF_DATA_TEMPLATE): vol.All(dict, cv.template_complex),
        vol.Optional(CONF_DATA_TYPES): vol.All(dict, cv.template_complex),
        vol.Optional(CONF_AUTHENTICATION): vol.In(
            [HTTP_BASIC_AUTHENTICATION, HTTP_DIGEST_AUTHENTICATION]
        ),
        vol.Optional(CONF_PASSWORD): cv.string,
        vol.Optional(CONF_USERNAME): cv.string,
        vol.Optional(CONF_VERIFY_SSL, default=DEFAULT_VERIFY_SSL): cv.boolean,
    }
)

_LOGGER = logging.getLogger(__name__)


async def async_get_service(
    hass: HomeAssistant,
    config: ConfigType,
    discovery_info: DiscoveryInfoType | None = None,
) -> RestNotificationService:
    """Get the RESTful notification service."""
    resource: str = config[CONF_RESOURCE]
    method: str = config[CONF_METHOD]
    headers: dict[str, str] | None = config.get(CONF_HEADERS)
    params: dict[str, str] | None = config.get(CONF_PARAMS)
    message_param_name: str = config[CONF_MESSAGE_PARAMETER_NAME]
    title_param_name: str | None = config.get(CONF_TITLE_PARAMETER_NAME)
    target_param_name: str | None = config.get(CONF_TARGET_PARAMETER_NAME)
    data: dict[str, Any] | None = config.get(CONF_DATA)
    data_template: dict[str, Any] | None = config.get(CONF_DATA_TEMPLATE)
    data_types: dict[str, Any] | None = config.get(CONF_DATA_TYPES)
    username: str | None = config.get(CONF_USERNAME)
    password: str | None = config.get(CONF_PASSWORD)
    verify_ssl: bool = config[CONF_VERIFY_SSL]
    auth: httpx.Auth | None = None
    if username and password:
        if config.get(CONF_AUTHENTICATION) == HTTP_DIGEST_AUTHENTICATION:
            auth = httpx.DigestAuth(username, password)
        else:
            auth = httpx.BasicAuth(username, password)

    return RestNotificationService(
        hass,
        resource,
        method,
        headers,
        params,
        message_param_name,
        title_param_name,
        target_param_name,
        data,
        data_template,
        auth,
        verify_ssl,
        data_types,
    )


class RestNotificationService(BaseNotificationService):
    """Implementation of a notification service for REST."""

    def __init__(
        self,
        hass: HomeAssistant,
        resource: str,
        method: str,
        headers: dict[str, str] | None,
        params: dict[str, str] | None,
        message_param_name: str,
        title_param_name: str | None,
        target_param_name: str | None,
        data: dict[str, Any] | None,
        data_template: dict[str, Any] | None,
        auth: httpx.Auth | None,
        verify_ssl: bool,
        data_types: dict[str, Any] | None,
    ) -> None:
        """Initialize the service."""
        self._resource = resource
        self._hass = hass
        self._method = method.upper()
        self._headers = headers
        self._params = params
        self._message_param_name = message_param_name
        self._title_param_name = title_param_name
        self._target_param_name = target_param_name
        self._data = data
        self._data_template = data_template
        self._auth = auth
        self._verify_ssl = verify_ssl
        self._data_types = data_types if data_types else {}

    async def async_send_message(self, message: str = "", **kwargs: Any) -> None:
        """Send a message to a user."""
        data = {self._message_param_name: message}

        if self._title_param_name is not None:
            data[self._title_param_name] = kwargs.get(ATTR_TITLE, ATTR_TITLE_DEFAULT)

        if self._target_param_name is not None and ATTR_TARGET in kwargs:
            # Target is a list as of 0.29 and we don't want to break existing
            # integrations, so just return the first target in the list.
            data[self._target_param_name] = kwargs[ATTR_TARGET][0]

        if self._data_template or self._data:
            kwargs[ATTR_MESSAGE] = message

            def _data_template_creator(value: Any, data_type=None) -> Any:
                """Recursive template creator helper function."""
                if isinstance(value, list):
                    return [_data_template_creator(item) for item in value]
                if isinstance(value, dict):
                    return {
                        key: _data_template_creator(item, self._data_types.get(key))
                        for key, item in value.items()
                    }
                if not isinstance(value, Template):
                    result = value
                else:
                    value.hass = self._hass
                    result = value.async_render(kwargs, parse_result=False)
                    _LOGGER.debug(
                        "_data_template_creator(value=%s) value.async_render()=%s of type=%s",
                        value,
                        result,
                        type(result),
                    )
                if not data_type:
                    return result
                str_to_type = {
                    "int": int,
                    "float": float,
                    "bool": bool,
                    "str": str,
                }
                if data_type not in str_to_type:
                    _LOGGER.warning("Ignoring unsupported data type: %s", data_type)
                elif isinstance(result, str_to_type[data_type]):
                    _LOGGER.debug(
                        "_data_template_creator: data_type=%s already type(result)=%s result=%s",
                        data_type,
                        type(result),
                        result,
                    )
                else:
                    _LOGGER.debug(
                        "_data_template_creator: data_type=%s before type(result)=%s result=%s",
                        data_type,
                        type(result),
                        result,
                    )
                    data_type = data_type.lower()
                    try:
                        if data_type == "int":
                            result = int(result)
                        elif data_type == "float":
                            result = float(result)
                        elif data_type == "bool":
                            result = result.lower() == "true"
                        elif data_type == "str":
                            pass
                        else:
                            _LOGGER.error("unknown data type: %s", data_type)
                            result = None
                    except ValueError:
                        _LOGGER.error("Cannot convert '%s' to %s", result, data_type)
                        result = None
                    _LOGGER.debug(
                        "_data_template_creator: data_type=%s after type(result)=%s result=%s",
                        data_type,
                        type(result),
                        result,
                    )
                return result

            if self._data:
                data.update(_data_template_creator(self._data))
            if self._data_template:
                data.update(_data_template_creator(self._data_template))

        websession = get_async_client(self._hass, self._verify_ssl)
        if self._method == "POST":
            response = await websession.post(
                self._resource,
                headers=self._headers,
                params=self._params,
                data=data,
                timeout=10,
                auth=self._auth or httpx.USE_CLIENT_DEFAULT,
            )
        elif self._method == "POST_JSON":
            _LOGGER.debug("async_send_message() POSTing JSON data=%s", data)
            response = await websession.post(
                self._resource,
                headers=self._headers,
                params=self._params,
                json=data,
                timeout=10,
                auth=self._auth or httpx.USE_CLIENT_DEFAULT,
            )
        else:  # default GET
            response = await websession.get(
                self._resource,
                headers=self._headers,
                params={**self._params, **data} if self._params else data,
                timeout=10,
                auth=self._auth,
            )

        if (
            response.status_code >= HTTPStatus.INTERNAL_SERVER_ERROR
            and response.status_code < 600
        ):
            _LOGGER.exception(
                "Server error. Response %d: %s:",
                response.status_code,
                response.reason_phrase,
            )
        elif (
            response.status_code >= HTTPStatus.BAD_REQUEST
            and response.status_code < HTTPStatus.INTERNAL_SERVER_ERROR
        ):
            _LOGGER.exception(
                "Client error. Response %d: %s:",
                response.status_code,
                response.reason_phrase,
            )
        elif (
            response.status_code >= HTTPStatus.OK
            and response.status_code < HTTPStatus.MULTIPLE_CHOICES
        ):
            _LOGGER.debug(
                "Success. Response %d: %s:",
                response.status_code,
                response.reason_phrase,
            )
            _LOGGER.debug("response.text=\n%s", response.text)
        else:
            _LOGGER.debug(
                "Response %d: %s:", response.status_code, response.reason_phrase
            )
