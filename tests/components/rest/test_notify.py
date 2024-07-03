"""The tests for the rest.notify platform."""

import json
import logging
from unittest.mock import patch

import pytest
import respx

from homeassistant import config as hass_config
from homeassistant.components import notify
from homeassistant.components.rest import DOMAIN
from homeassistant.components.rest.notify import (
    CONF_DATA_TEMPLATE,
    CONF_MESSAGE_PARAMETER_NAME,
    RestNotificationService,
    async_get_service,
)
from homeassistant.const import (
    CONF_HEADERS,
    CONF_METHOD,
    CONF_NAME,
    CONF_PLATFORM,
    CONF_RESOURCE,
    CONF_VERIFY_SSL,
    CONTENT_TYPE_JSON,
    SERVICE_RELOAD,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.template import Template
from homeassistant.setup import async_setup_component

from tests.common import get_fixture_path

_LOGGER = logging.getLogger(__name__)
_LOGGER.setLevel(logging.INFO)


@respx.mock
async def test_reload_notify(hass: HomeAssistant) -> None:
    """Verify we can reload the notify service."""
    respx.get("http://localhost") % 200

    assert await async_setup_component(
        hass,
        notify.DOMAIN,
        {
            notify.DOMAIN: [
                {
                    "name": DOMAIN,
                    "platform": DOMAIN,
                    "resource": "http://127.0.0.1/off",
                },
            ]
        },
    )
    await hass.async_block_till_done()

    assert hass.services.has_service(notify.DOMAIN, DOMAIN)

    yaml_path = get_fixture_path("configuration.yaml", "rest")

    with patch.object(hass_config, "YAML_CONFIG_FILE", yaml_path):
        await hass.services.async_call(
            DOMAIN,
            SERVICE_RELOAD,
            {},
            blocking=True,
        )
        await hass.async_block_till_done()

    assert not hass.services.has_service(notify.DOMAIN, DOMAIN)
    assert hass.services.has_service(notify.DOMAIN, "rest_reloaded")


@respx.mock
async def test_notify_data_types(hass: HomeAssistant) -> None:
    """Verify the correct data types are sent."""

    resource = "http://127.0.0.1/notify"
    route = respx.post(resource)

    # Create and cross-check the inputs and expected outputs.
    data_template = {
        "str1": "spam",
        "str2": Template('{{ "egg" }}', hass),
        "int1": 41,
        "int2": Template("{{ 42 }}", hass),
        "float1": 3.14156,
        "float2": Template("{{ 2.71828 }}", hass),
        "bool1": False,
        "bool2": Template("{{ True }}", hass),
    }
    expected_result = {
        "str1": {"value": "spam", "type": str},
        "str2": {"value": "egg", "type": str},
        "int1": {"value": 41, "type": int},
        "int2": {"value": 42, "type": int},
        "float1": {"value": 3.14156, "type": float},
        "float2": {"value": 2.71828, "type": float},
        "bool1": {"value": False, "type": bool},
        "bool2": {"value": True, "type": bool},
    }
    for key in data_template:
        assert expected_result[key] is not None

    # Create an instance of RestNotificationService using the dict of data templates.
    config = {
        CONF_PLATFORM: DOMAIN,
        CONF_NAME: "test_notify_data_types",
        CONF_RESOURCE: resource,
        CONF_METHOD: "POST_JSON",
        CONF_MESSAGE_PARAMETER_NAME: "message",
        CONF_DATA_TEMPLATE: data_template,
        CONF_VERIFY_SSL: False,
        CONF_HEADERS: {
            "Content-Type": CONTENT_TYPE_JSON,
        },
    }
    rns: RestNotificationService = await async_get_service(
        hass,
        config=config,
    )
    await hass.async_block_till_done()

    # Send an HTTP request and confirm that it was mocked by RESPX.
    await rns.async_send_message(message="my message")
    await hass.async_block_till_done()
    assert route.called

    # Retrieve the most recent request content and convert it from stringified json to a dict for ready access.
    try:
        request_content = json.loads(route.calls.last.request.content)
    except json.JSONDecodeError:
        _LOGGER.error(
            "Request content is invalid JSON: %s", route.calls.last.request.content
        )
        pytest.fail("request content is invalid JSON")
    assert isinstance(request_content, dict)

    # Compare the (now dict) request content to the original data template.
    assert len(request_content) == len(data_template) + 1  # The +1 is for "message".
    for key, value in data_template.items():
        _LOGGER.debug(
            "key=%s request_content[key]=%s data_template[key]=%s type(request_content[key])=%s type(data_template[key])=%s",
            key,
            request_content[key],
            value,
            type(request_content[key]),
            type(value),
        )
        assert isinstance(
            request_content[key], expected_result[key]["type"]
        ), "incorrect type"
        assert request_content[key] == expected_result[key]["value"], "incorrect value"
