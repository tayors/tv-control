import copy
import unittest

from sensor_policy import DEFAULT_CONFIG, evaluate, target_for_lux, validate_config


def sample(**changes):
    value = {
        "awake": True,
        "lux": 34,
        "sensor_age_seconds": 0,
        "picture_mode": 3,
        "hdr_setting": 0,
        "backlight": 34,
        "adaptive_brightness": 1,
    }
    value.update(changes)
    return value


class SensorPolicyTests(unittest.TestCase):
    def test_interpolation_and_anchor_clamping(self):
        self.assertEqual(target_for_lux({}, 0), 34)
        self.assertEqual(target_for_lux({}, 34), 34)
        self.assertEqual(target_for_lux({}, 175), 55)
        self.assertEqual(target_for_lux({}, 500), 55)
        self.assertEqual(target_for_lux({}, 104.5), 45)

    def test_ineligible_samples_do_not_apply(self):
        cases = [
            (sample(awake=False), "tv_off"),
            (sample(sensor_age_seconds=31), "stale_sensor"),
            (sample(lux=None), "invalid_sensor"),
            (sample(picture_mode=9), "unsupported_picture_mode"),
            (sample(backlight=86), "high_backlight"),
            (sample(adaptive_brightness=0), "adaptive_brightness_off"),
        ]
        for observed, reason in cases:
            with self.subTest(reason=reason):
                _, decision = evaluate({}, {}, observed, 100)
                self.assertEqual(decision, {"action": "skip", "reason": reason})

    def test_median_smoothing_and_deadband(self):
        state = {}
        state, _ = evaluate({}, state, sample(lux=34), 1)
        state["last_expected"] = 34
        state, _ = evaluate({}, state, sample(lux=175), 2)
        state["last_expected"] = 34
        _, decision = evaluate({}, state, sample(lux=34), 3)
        self.assertEqual(decision["lux"], 34)
        self.assertEqual(decision["action"], "none")
        self.assertEqual(decision["reason"], "deadband")

    def test_steps_are_bounded_in_both_directions(self):
        _, upward = evaluate({}, {}, sample(lux=175), 1)
        self.assertEqual(upward["target"], 37)
        down_state = {"last_context": [3, 0], "last_expected": 55}
        _, downward = evaluate({}, down_state, sample(lux=0, backlight=55), 1)
        self.assertEqual(downward["target"], 52)

    def test_external_change_starts_manual_hold(self):
        state = {"last_context": [3, 0], "last_expected": 34}
        new_state, decision = evaluate({}, state, sample(backlight=40), 10)
        self.assertEqual(decision, {"action": "skip", "reason": "manual_override"})
        self.assertEqual(new_state["hold_until"], 3610)
        self.assertIsNone(new_state["last_expected"])

    def test_context_change_does_not_look_like_manual_override(self):
        state = {"last_context": [3, 1], "last_expected": 70}
        new_state, decision = evaluate({}, state, sample(backlight=34), 10)
        self.assertNotEqual(decision.get("reason"), "manual_override")
        self.assertEqual(new_state["last_context"], [3, 0])
        self.assertEqual(new_state["last_expected"], 34)

    def test_hold_expires_and_policy_resumes(self):
        state = {"last_context": [3, 0], "last_expected": None, "hold_until": 10}
        _, held = evaluate({}, state, sample(lux=175), 9)
        self.assertEqual(held, {"action": "skip", "reason": "manual_hold"})
        new_state, resumed = evaluate({}, state, sample(lux=175), 10)
        self.assertEqual(resumed["action"], "apply")
        self.assertEqual(new_state["last_expected"], 34)

    def test_evaluate_does_not_mutate_inputs(self):
        config = copy.deepcopy(DEFAULT_CONFIG)
        state = {"lux_samples": [{"time": 1, "lux": 20}]}
        observed = sample(lux=175)
        originals = copy.deepcopy((config, state, observed))
        evaluate(config, state, observed, 2)
        self.assertEqual((config, state, observed), originals)

    def test_apply_keeps_expected_at_actual_until_write_is_verified(self):
        state, decision = evaluate({}, {}, sample(lux=175), 1)
        self.assertEqual(decision["action"], "apply")
        self.assertEqual(state["last_expected"], 34)

    def test_old_samples_are_discarded_and_only_three_are_kept(self):
        state = {
            "lux_samples": [
                {"time": 1, "lux": 1},
                {"time": 70, "lux": 70},
                {"time": 80, "lux": 80},
                {"time": 90, "lux": 90},
            ]
        }
        new_state, _ = evaluate({}, state, sample(lux=100), 100)
        self.assertEqual([x["lux"] for x in new_state["lux_samples"]], [80.0, 90.0, 100.0])

    def test_invalid_configs_raise(self):
        invalid = [
            {"bright_lux": 34},
            {"dim_brightness": 56},
            {"max_step": 0},
            {"deadband": -1},
            {"allowed_picture_modes": []},
            {"max_eligible_backlight": 101},
            {"manual_hold_seconds": -1},
        ]
        for overrides in invalid:
            with self.subTest(overrides=overrides):
                config = dict(DEFAULT_CONFIG)
                config.update(overrides)
                with self.assertRaises(ValueError):
                    validate_config(config)


if __name__ == "__main__":
    unittest.main()
