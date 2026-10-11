"""Climate and running-state reporting across the grill's power states."""
from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING

import pytest

from custom_components.gmg.api import FireState, PowerState

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from pytest_homeassistant_custom_component.common import MockConfigEntry


def _one(hass: HomeAssistant, domain: str, suffix: str = ""):
    states = [s for s in hass.states.async_all(domain) if s.entity_id.endswith(suffix)]
    assert len(states) == 1, [s.entity_id for s in states]
    return states[0]


@pytest.mark.parametrize(
    ("power", "fire", "mode", "action", "cooking"),
    [
        (PowerState.ON, FireState.RUNNING, "heat", "heating", "on"),
        (PowerState.ON, FireState.STARTUP, "heat", "idle", "on"),
        # Shutdown: the firmware's fan cool-down after power-off.
        (PowerState.FAN, FireState.COOL_DOWN, "off", "fan", "off"),
        (PowerState.OFF, FireState.OFF, "off", "off", "off"),
    ],
)
async def test_power_states(  # noqa: PLR0917 - pytest fixtures + params
    hass: HomeAssistant,
    mock_client,
    mock_grill_info,
    mock_config_entry: MockConfigEntry,
    power: PowerState,
    fire: FireState,
    mode: str,
    action: str,
    cooking: str,
) -> None:
    snap = dataclasses.replace(
        mock_grill_info.snapshot,
        power_state=power,
        fire_state=fire,
        flame_on=fire is FireState.RUNNING,
    )
    mock_client.async_probe.return_value = dataclasses.replace(mock_grill_info, snapshot=snap)
    mock_client.async_poll.return_value = snap
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    climate = _one(hass, "climate")
    assert climate.state == mode
    assert climate.attributes["hvac_action"] == action
    assert _one(hass, "binary_sensor", "_cooking").state == cooking
