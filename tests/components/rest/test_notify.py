"""The tests for the rest.notify platform."""

import json
import logging
from unittest.mock import patch

import pytest
import respx

from homeassistant import config as hass_config
from homeassistant.components import notify
from homeassistant.components.rest import DOMAIN
from homeassistant.components.rest.const import CONF_PAYLOAD_TEMPLATE
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
_LOGGER.setLevel(logging.DEBUG)
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
        "str1": Template('{{ "spam" }}', hass),
        "int1": Template("{{ 40 + 2 }}", hass),
        "bool1": Template("{{ False }}", hass),
        "none1": Template("{{ None }}", hass),
    }
    expected_results = {
        "message": {"value": "my message", "type": str},
        "str1": {"value": "spam", "type": str},
        "int1": {"value": 42, "type": int},
        "bool1": {"value": False, "type": bool},
        "none1": {"value": None, "type": None},
    }
    assert len(data_template) + 1 == len(expected_results)  # The +1 is for "message".
    for key in data_template:
        assert expected_results[key] is not None

    # Consider a payload_template containing the message plus everything from data_template.
    payload_template = "{{ '{ \"message\": \"' ~ message ~ '\", \"str1\": \"' ~ str1 ~ '\", \"int1\": ' ~ int1 ~ ', \"bool1\": ' ~ (bool1|lower) ~ ', \"none1\": ' ~ iif(none1=='None','null',none1) ~ ' }' }}"
    _LOGGER.debug("payload_template=%s", payload_template)

    # Create an instance of RestNotificationService using the dict of data templates and the payload template.
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
        CONF_PAYLOAD_TEMPLATE: Template(payload_template, hass),
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
    _LOGGER.debug(
        "type(request_content)=%s request_content=%s",
        type(request_content),
        request_content,
    )
    assert isinstance(request_content, dict)

    # Compare the (now dict) request content to the original data template.
    assert len(request_content) == len(expected_results)
    for key, value in request_content.items():
        _LOGGER.debug(
            "key=%s type(value)=%s expected_results[key]['type']=%s value=%s expected_results[key]['value']=%s",
            key,
            type(value),
            expected_results[key]["type"],
            value,
            expected_results[key]["value"],
        )
        if expected_results[key]["value"] is not None:
            assert isinstance(value, expected_results[key]["type"]), "incorrect type"
        assert value == expected_results[key]["value"], "incorrect value for key=" + key

    pytest.fail("THE END")
