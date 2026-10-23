"""Pure sensor-to-backlight policy for the TV controller."""

from __future__ import annotations

import copy
import math
import statistics
from typing import Any
from comfort_policy import remembered_point


DEFAULT_CONFIG = {
    "dim_lux": 34,
    "bright_lux": 175,
    "dim_brightness": 34,
    "bright_brightness": 55,
    "max_step": 3,
    "deadband": 2,
    "max_sensor_age_seconds": 30,
    "allowed_picture_modes": [3],
    "max_eligible_backlight": 85,
    "manual_hold_seconds": 3600,
}


def _config(config: dict[str, Any]) -> dict[str, Any]:
    merged = dict(DEFAULT_CONFIG)
    merged.update(config)
    validate_config(merged)
    return merged


def _number(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be numeric")
    value = float(value)
    if not math.isfinite(value):
        raise ValueError(f"{name} must be finite")
    return value


def validate_config(config: dict[str, Any]) -> None:
    """Raise ValueError when a policy configuration is invalid."""
    required = set(DEFAULT_CONFIG)
    if config.get('strategy', 'curve') not in ('curve', 'learned'):
        raise ValueError('strategy must be curve or learned')
    missing = required.difference(config)
    if missing:
        raise ValueError(f"missing config fields: {', '.join(sorted(missing))}")

    dim_lux = _number(config["dim_lux"], "dim_lux")
    bright_lux = _number(config["bright_lux"], "bright_lux")
    dim_brightness = _number(config["dim_brightness"], "dim_brightness")
    bright_brightness = _number(config["bright_brightness"], "bright_brightness")
    max_step = _number(config["max_step"], "max_step")
    deadband = _number(config["deadband"], "deadband")
    max_age = _number(config["max_sensor_age_seconds"], "max_sensor_age_seconds")
    max_backlight = _number(config["max_eligible_backlight"], "max_eligible_backlight")
    hold_seconds = _number(config["manual_hold_seconds"], "manual_hold_seconds")

    if dim_lux < 0 or bright_lux <= dim_lux:
        raise ValueError("lux anchors must be non-negative and strictly increasing")
    if not 5 <= dim_brightness <= bright_brightness <= 85:
        raise ValueError("automation brightness anchors must satisfy 5 <= dim <= bright <= 85")
    for key in ("dim_brightness", "bright_brightness", "max_step", "deadband"):
        if type(config[key]) is not int:
            raise ValueError(f"{key} must be an integer")
    if max_step <= 0 or max_step > 100:
        raise ValueError("max_step must be in (0, 100]")
    if deadband < 1 or deadband > 100:
        raise ValueError("deadband must be in [1, 100]")
    if max_age < 0:
        raise ValueError("max_sensor_age_seconds must be non-negative")
    if not 0 <= max_backlight <= 100:
        raise ValueError("max_eligible_backlight must be in [0, 100]")
    if hold_seconds < 0:
        raise ValueError("manual_hold_seconds must be non-negative")

    modes = config["allowed_picture_modes"]
    if not isinstance(modes, list) or not modes:
        raise ValueError("allowed_picture_modes must be a non-empty list")
    if any(isinstance(mode, bool) or not isinstance(mode, int) or mode < 0 for mode in modes):
        raise ValueError("allowed_picture_modes must contain non-negative integers")


def target_for_lux(config: dict[str, Any], lux: float) -> int:
    """Return the linearly interpolated brightness, clamped at both lux anchors."""
    cfg = _config(config)
    measured = _number(lux, "lux")
    if measured <= cfg["dim_lux"]:
        return int(cfg["dim_brightness"])
    if measured >= cfg["bright_lux"]:
        return int(cfg["bright_brightness"])
    ratio = (measured - cfg["dim_lux"]) / (cfg["bright_lux"] - cfg["dim_lux"])
    target = cfg["dim_brightness"] + ratio * (
        cfg["bright_brightness"] - cfg["dim_brightness"]
    )
    return int(math.floor(target + 0.5))


def _skip(reason: str) -> dict[str, Any]:
    return {"action": "skip", "reason": reason}


def evaluate(
    config: dict[str, Any],
    state: dict[str, Any],
    sample: dict[str, Any],
    now: float,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Evaluate one sample without mutating config, state, or sample."""
    cfg = _config(config)
    current_state = copy.deepcopy(state)
    current_sample = copy.deepcopy(sample)
    timestamp = _number(now, "now")

    samples = []
    for entry in current_state.get("lux_samples", []):
        try:
            entry_time = _number(entry["time"], "sample time")
            entry_lux = _number(entry["lux"], "sample lux")
        except (KeyError, TypeError, ValueError):
            continue
        if entry_lux >= 0 and 0 <= timestamp - entry_time <= 60:
            samples.append({"time": entry_time, "lux": entry_lux})
    current_state["lux_samples"] = samples[-3:]

    if not current_sample.get("awake"):
        return current_state, _skip("tv_off")
    if current_state.get('feedback_in_flight'):
        return current_state, _skip('feedback_incomplete')

    lux = current_sample.get("lux")
    age = current_sample.get("sensor_age_seconds")
    try:
        measured_lux = _number(lux, "lux")
        sensor_age = _number(age, "sensor_age_seconds")
    except ValueError:
        return current_state, _skip("invalid_sensor")
    if measured_lux < 0 or sensor_age < 0:
        return current_state, _skip("invalid_sensor")
    if sensor_age > cfg["max_sensor_age_seconds"]:
        return current_state, _skip("stale_sensor")

    mode = current_sample.get("picture_mode")
    hdr_setting = current_sample.get("hdr_setting")
    context = [mode, hdr_setting]
    if current_state.get("last_context") != context:
        current_state["last_context"] = context
        current_state["last_expected"] = None

    if mode not in cfg["allowed_picture_modes"]:
        return current_state, _skip("unsupported_picture_mode")

    backlight = current_sample.get("backlight")
    if isinstance(backlight, bool) or not isinstance(backlight, int) or not 0 <= backlight <= 100:
        return current_state, _skip("invalid_backlight")
    if backlight > cfg["max_eligible_backlight"]:
        return current_state, _skip("high_backlight")
    if current_sample.get("adaptive_brightness") != 1:
        return current_state, _skip("adaptive_brightness_off")

    hold_until = current_state.get("hold_until", 0)
    try:
        hold_until = _number(hold_until, "hold_until")
    except ValueError:
        hold_until = 0
    if timestamp < hold_until:
        return current_state, _skip("manual_hold")
    current_state["hold_until"] = 0

    expected = current_state.get("last_expected")
    if expected is not None and backlight != expected:
        current_state["hold_until"] = timestamp + cfg["manual_hold_seconds"]
        current_state["last_expected"] = None
        return current_state, _skip("manual_override")
    if expected is None:
        current_state["last_expected"] = backlight

    current_state["lux_samples"].append({"time": timestamp, "lux": measured_lux})
    current_state["lux_samples"] = current_state["lux_samples"][-3:]
    smoothed_lux = float(
        statistics.median(entry["lux"] for entry in current_state["lux_samples"])
    )
    learned = cfg.get('strategy') == 'learned'
    if learned:
        memory = current_state.get('comfort', {})
        if memory.get('pending'):
            return current_state, _skip('awaiting_comfort')
        point = remembered_point(memory, smoothed_lux, context)
        if point is None:
            return current_state, _skip('unlearned_light')
        curve_target = point['brightness']
    else:
        curve_target = target_for_lux(cfg, smoothed_lux)
    delta = curve_target - backlight
    common = {"curve_target": curve_target, "lux": smoothed_lux}
    if learned:
        common.update(target_source='comfort_feedback', learned_at=point.get('time'), learned_lux=point['lux'])
    if abs(delta) < cfg["deadband"]:
        return current_state, {"action": "none", "reason": "deadband", **common}

    step = min(abs(delta), cfg["max_step"])
    target = int(backlight + (step if delta > 0 else -step))
    return current_state, {
        "action": "apply",
        "reason": "bounded_step",
        "target": target,
        **common,
    }
