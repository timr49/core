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
    CONF_DATA_TYPES,
    CONF_MESSAGE_PARAMETER_NAME,
    CONF_TARGET_PARAMETER_NAME,
    CONF_TITLE_PARAMETER_NAME,
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
logging.getLogger("homeassistant.components.rest.notify").setLevel(logging.DEBUG)


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
        "str3": "39",
        "str4": Template('{{ "40" }}', hass),
        "str5": Template('{{ "True" }}', hass),
        "int1": 41,
        "int2": Template("{{ 42 }}", hass),
        "int3": Template("{{ 40 + 3 }}", hass),
        "int4": "4x4",  # The string is not an integer.
        "float1": 3.14159,
        "float2": Template("{{ 2.71828 }}", hass),
        "float3": "1.61803",
        "bool1": False,
        "bool2": Template("{{ True }}", hass),
        "bool3": Template("{{ not True }}", hass),
    }
    data_types = {
        "int1": "int",
        "int2": "int",
        "int3": "int",
        "int4": "int",
        "float1": "float",
        "float2": "float",
        "float3": "float",
        "bool1": "bool",
        "bool2": "bool",
        "bool3": "boolean",  # Type "boolean" is not supported.
    }
    expected_result = {
        "str1": {"value": "spam", "type": str},
        "str2": {"value": "egg", "type": str},
        "str3": {"value": "39", "type": str},
        "str4": {"value": "40", "type": str},
        "str5": {"value": "True", "type": str},
        "int1": {"value": 41, "type": int},
        "int2": {"value": 42, "type": int},
        "int3": {"value": 43, "type": int},
        # The string is not an integer so there is no conversion.
        "int4": {"value": "4x4", "type": str},
        "float1": {"value": 3.14159, "type": float},
        "float2": {"value": 2.71828, "type": float},
        "float3": {"value": 1.61803, "type": float},
        "bool1": {"value": False, "type": bool},
        "bool2": {"value": True, "type": bool},
        # Type "boolean" is not supported so there is no conversion from rendered string.
        "bool3": {"value": "False", "type": str},
    }
    config = {
        CONF_PLATFORM: DOMAIN,
        CONF_NAME: "test_notify_data_types",
        CONF_RESOURCE: resource,
        CONF_METHOD: "POST_JSON",
        CONF_MESSAGE_PARAMETER_NAME: "message",
        CONF_TITLE_PARAMETER_NAME: "title",
        CONF_TARGET_PARAMETER_NAME: "target",
        CONF_DATA_TEMPLATE: data_template,
        CONF_DATA_TYPES: data_types,
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
    await rns.async_send_message(
        message="my message",
        title="My Title",
        target=["mytarget"],
    )
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
    assert (
        len(request_content)
        == len(data_template) + 3  # The +3 is for "message"+"title"+"target"
    )
    for key, value in expected_result.items():
        _LOGGER.debug(
            "key=%s request_content[key]=%s expected value=%s type(request_content[key])=%s expected type=%s",
            key,
            request_content[key],
            value["value"],
            type(request_content[key]),
            value["type"],
        )
        if value["type"] is not None:
            assert isinstance(
                request_content[key], value["type"]
            ), f"incorrect type: expected {value['type']} but got {type(request_content[key])}"
        assert (
            request_content[key] == value["value"]
        ), f"incorrect value: expected {value['value']} but got {request_content[key]}"


#    pytest.fail("THE END"). # Force output of stdout, logging, etc.
