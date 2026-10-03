"""Tests for the GMG wire protocol parser and command builders.

Frame offsets follow ``parse_status_frame`` (the layout confirmed against a
live Jim Bowie), not the older byte table that sat 4 bytes short after offset 8.
Imports are hard: a rename must fail the suite rather than silently skip it.
"""
from __future__ import annotations

import struct

import pytest

from custom_components.gmg.api import GMGSnapshot
from custom_components.gmg.api.protocol import (
    GMGInvalidValueError,
    GMGProtocolError,
    parse_status_frame,
)
from custom_components.gmg.api.protocol import (
    encode_set_grill_temp as build_set_grill_temp,
)
from custom_components.gmg.api.protocol import (
    encode_set_probe_target as build_set_probe_target,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _u16(value: int) -> bytes:
    return struct.pack("<H", value)


def _u32(value: int) -> bytes:
    return struct.pack("<I", value)


def _make_frame(
    *,
    header: bytes = b"\x55\x52",
    grill_temp: int = 225,
    probe_1: int = 140,
    grill_set: int = 225,
    api_version: int = 1,
    build: bytes = b"\x00\x00\x00",
    probe_2: int = 89,
    probe_2_set: int = 145,
    profile_remaining: int = 0,
    warn_code: int = 0,
    probe_1_set: int = 165,
    power_state: int = 1,
    grill_mode: int = 0,
    fire_state: int = 3,
    hopper_pct: int = 80,
    profile_end: int = 0,
    grill_type: int = 3,
) -> bytes:
    """Construct a 36-byte status frame with the given field values."""
    frame = bytearray()
    frame += header                       # 0..1
    frame += _u16(grill_temp)             # 2..3
    frame += _u16(probe_1)                # 4..5
    frame += _u16(grill_set)              # 6..7
    frame += bytes([api_version])         # 8
    frame += build                        # 9..11
    frame += bytes(4)                     # 12..15 reserved
    frame += _u16(probe_2)                # 16..17
    frame += _u16(probe_2_set)            # 18..19
    frame += _u32(profile_remaining)      # 20..23
    frame += _u32(warn_code)              # 24..27
    frame += _u16(probe_1_set)            # 28..29
    frame += bytes([power_state])         # 30
    frame += bytes([grill_mode])          # 31
    frame += bytes([fire_state])          # 32
    frame += bytes([hopper_pct])          # 33
    frame += bytes([profile_end])         # 34
    frame += bytes([grill_type])          # 35
    assert len(frame) == 36
    return bytes(frame)


# ---------------------------------------------------------------------------
# Parse tests
# ---------------------------------------------------------------------------


def test_parse_baseline_frame() -> None:
    frame = _make_frame(
        grill_temp=225,
        probe_1=140,
        grill_set=225,
        power_state=1,
        fire_state=3,
        warn_code=0,
    )
    snap: GMGSnapshot = parse_status_frame(frame)

    assert snap.grill_temp == 225
    assert snap.grill_set_temp == 225
    assert snap.probe_1_temp == 140
    assert snap.probe_1_target == 165
    assert int(snap.power_state) == 1
    assert int(snap.fire_state) == 3
    assert snap.flame_on is True
    assert snap.low_pellet is False
    assert snap.cold_smoke is False


def test_parse_probe_sentinel_means_unplugged() -> None:
    frame = _make_frame(probe_1=89)
    snap = parse_status_frame(frame)
    assert snap.probe_1_temp is None


def test_parse_probe_2_fields_at_offset_16() -> None:
    snap = parse_status_frame(_make_frame(probe_2=150, probe_2_set=203))
    assert snap.probe_2_temp == 150
    assert snap.probe_2_target == 203


@pytest.mark.parametrize("raw", [558, 601, 0xFFFF])
def test_parse_probe_above_upper_guard_means_unplugged(raw: int) -> None:
    """Empty socket on Jim Bowie fw UNDB02SUC0_1.6 reads 601 degF, not 89."""
    snap = parse_status_frame(_make_frame(probe_1=raw, probe_2=raw))
    assert snap.probe_1_temp is None
    assert snap.probe_2_temp is None


def test_parse_probe_at_upper_guard_is_kept() -> None:
    assert parse_status_frame(_make_frame(probe_1=557)).probe_1_temp == 557


def test_parse_live_jim_bowie_snapshot() -> None:
    """Live cook: pit 223F / set 223F, probe 1 163F (no target), probe 2 empty."""
    snap = parse_status_frame(
        _make_frame(
            grill_temp=223, grill_set=223, probe_1=163, probe_1_set=0,
            probe_2=601, probe_2_set=0, power_state=1, fire_state=3, grill_type=3,
        )
    )
    assert (snap.grill_temp, snap.grill_set_temp, snap.probe_1_temp) == (223, 223, 163)
    assert snap.probe_2_temp is None
    assert snap.probe_1_target == 0
    assert snap.flame_on is True


def test_parse_low_pellet_code_8() -> None:
    frame = _make_frame(warn_code=8)
    snap = parse_status_frame(frame)
    assert snap.low_pellet is True


def test_parse_low_pellet_code_128_alias() -> None:
    frame = _make_frame(warn_code=128)
    snap = parse_status_frame(frame)
    assert snap.low_pellet is True


def test_parse_cold_smoke_power_state() -> None:
    frame = _make_frame(power_state=3)
    snap = parse_status_frame(frame)
    assert snap.cold_smoke is True


def test_parse_short_frame_raises() -> None:
    with pytest.raises(GMGProtocolError):
        parse_status_frame(b"\x55\x52\x00\x00")


def test_parse_wrong_header_raises() -> None:
    frame = _make_frame(header=b"\x00\x00")
    with pytest.raises(GMGProtocolError):
        parse_status_frame(frame)


# ---------------------------------------------------------------------------
# Command builder tests
# ---------------------------------------------------------------------------


def test_build_set_grill_temp_basic() -> None:
    assert build_set_grill_temp(225) == b"UT225!"


def test_build_set_probe_target_probe_1_uppercase() -> None:
    assert build_set_probe_target(1, 165) == b"UF165!"


def test_build_set_probe_target_probe_2_lowercase() -> None:
    assert build_set_probe_target(2, 145) == b"Uf145!"


@pytest.mark.parametrize("bad_temp", [-1, 0, 149, 551, 1000])
def test_build_set_grill_temp_out_of_range_raises(bad_temp: int) -> None:
    with pytest.raises(GMGInvalidValueError):
        build_set_grill_temp(bad_temp)


@pytest.mark.parametrize("bad_temp", [-1, 0, 31, 258, 999])
def test_build_set_probe_target_out_of_range_raises(bad_temp: int) -> None:
    with pytest.raises(GMGInvalidValueError):
        build_set_probe_target(1, bad_temp)
