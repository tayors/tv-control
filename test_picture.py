import unittest
import json
from pathlib import Path
import tempfile
from unittest.mock import patch

from picture import NativePicture, SDK_SHA256, DEFAULT_CONFIG, record_feedback, undo_feedback
from sensor_policy import evaluate


class FakeTV:
    def __init__(self, digest=SDK_SHA256, response="Result: Parcel(00000000 00000022 '....')"):
        self.digest = digest
        self.response = response
        self.calls = []

    def shell(self, *args):
        self.calls.append(args)
        if args[0] == 'sha256sum':
            return self.digest + ' framework.jar'
        return self.response


class SimulatedNative(NativePicture):
    def __init__(self, stuck=False):
        self.current_context = [3, 1]
        self.level = 34
        self.writes = []
        self.stuck = stuck

    def context(self):
        return self.current_context

    def sample(self):
        return {'awake': True, 'lux': 10, 'sensor_age_seconds': 0, 'picture_mode': self.current_context[0],
                'hdr_setting': self.current_context[1], 'backlight': self.level, 'adaptive_brightness': 1}

    def call(self, transaction, *values):
        if transaction == 101:
            return self.level
        if transaction == 100:
            self.writes.append(values)
            if not self.stuck:
                self.level = values[1]
            return 1
        raise AssertionError(transaction)


class NativePictureTests(unittest.TestCase):
    def test_firmware_mismatch_blocks_all_transactions(self):
        tv = FakeTV(digest='different')
        with self.assertRaisesRegex(RuntimeError, 'SDK changed'):
            NativePicture(tv).call(101)
        self.assertEqual(len(tv.calls), 1)
        self.assertEqual(tv.calls[0][0], 'sha256sum')

    def test_parcel_value_and_rejected_exception(self):
        self.assertEqual(NativePicture(FakeTV()).call(101), 34)
        with self.assertRaisesRegex(RuntimeError, 'Binder response'):
            NativePicture(FakeTV(response='Result: Parcel(ffffffff 00000000)')).call(101)

    @patch('picture.time.sleep')
    def test_verified_write_changes_only_current_context(self, _sleep):
        native = SimulatedNative()
        native.set_backlight(37, [3, 1])
        self.assertEqual(native.level, 37)
        self.assertEqual(native.writes, [(0, 37, 2)])

    @patch('picture.time.sleep')
    def test_failed_readback_attempts_rollback(self, _sleep):
        native = SimulatedNative(stuck=True)
        with self.assertRaisesRegex(RuntimeError, 'did not settle'):
            native.set_backlight(37, [3, 1])
        self.assertEqual(native.writes, [(0, 37, 2), (0, 34, 2)])

    def test_context_change_and_high_brightness_block_write(self):
        native = SimulatedNative()
        native.current_context = [53, 1]
        with self.assertRaises(RuntimeError):
            native.set_backlight(37, [3, 1])
        native.current_context = [3, 1]
        native.level = 100
        with self.assertRaises(RuntimeError):
            native.set_backlight(37, [3, 1])
        self.assertEqual(native.writes, [])

    def test_sleeping_tv_never_queries_picture_service(self):
        tv = FakeTV(response='mWakefulness=Asleep')
        self.assertEqual(NativePicture(tv).sample(), {'awake': False})
        self.assertEqual(tv.calls, [('dumpsys', 'power')])


class ComfortFeedbackTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.state_path = Path(temporary.name) / 'state.json'
        self.addCleanup(patch.stopall)
        patch('picture.STATE', self.state_path).start()
        patch('picture.time.sleep').start()
        self.native = SimulatedNative()
        self.config = {**DEFAULT_CONFIG, 'strategy': 'learned'}
        self.state = {'enabled': True}

    def test_nudge_then_confirm_is_persisted_and_reused_without_old_curve(self):
        result = record_feedback(self.native, self.state, self.config, 'too-bright')
        self.assertEqual(self.native.level, 31)
        self.assertEqual(result['state']['comfort']['points'], [])
        confirmed = record_feedback(self.native, result['state'], self.config, 'comfortable')
        self.assertEqual(len(self.native.writes), 1)  # Comfortable itself never writes brightness.
        persisted = json.loads(self.state_path.read_text())
        self.assertEqual(persisted['comfort']['points'][0]['brightness'], 31)
        resumed_state = {**persisted, 'last_expected': None}
        _, decision = evaluate(self.config, resumed_state, {**self.native.sample(), 'backlight': 40}, 100)
        self.assertEqual(decision['curve_target'], 31)
        self.assertEqual(confirmed['state']['enabled'], True)

    def test_undo_restores_picture_and_learning_after_restart(self):
        record_feedback(self.native, self.state, self.config, 'too-dark')
        persisted = json.loads(self.state_path.read_text())
        restored = undo_feedback(self.native, persisted, self.config)
        self.assertEqual(self.native.level, 34)
        self.assertEqual(restored['state']['comfort']['points'], [])
        self.assertNotIn('feedback_undo', restored['state'])
        self.assertTrue(restored['state']['enabled'])

    def test_undo_never_overwrites_a_newer_manual_picture_change(self):
        result = record_feedback(self.native, self.state, self.config, 'too-bright')
        self.native.level = 45
        restored = undo_feedback(self.native, result['state'], self.config)
        self.assertEqual(self.native.level, 45)
        self.assertEqual(len(self.native.writes), 1)
        self.assertGreater(restored['state']['hold_until'], 0)

    def test_feedback_does_not_enable_a_paused_controller(self):
        result = record_feedback(self.native, {'enabled': False}, self.config, 'comfortable')
        self.assertFalse(result['state']['enabled'])
        self.assertEqual(self.native.writes, [])

    def test_bad_sample_does_not_write_or_learn(self):
        for changes in ({'sensor_age_seconds': 99}, {'picture_mode': 53}, {'lux': None}, {'backlight': 99}):
            with self.subTest(changes=changes), patch.object(self.native, 'sample', return_value={**self.native.sample(), **changes}):
                with self.assertRaises(RuntimeError):
                    record_feedback(self.native, self.state, self.config, 'comfortable')
        self.assertFalse(self.state_path.exists())
        self.assertEqual(self.native.writes, [])

    def test_failed_adjustment_blocks_automation_and_retains_recovery(self):
        self.native.stuck = True
        with self.assertRaises(RuntimeError):
            record_feedback(self.native, self.state, self.config, 'too-dark')
        persisted = json.loads(self.state_path.read_text())
        self.assertTrue(persisted['feedback_in_flight'])
        self.assertFalse(persisted['enabled'])
        self.assertEqual(persisted['comfort']['points'], [])
        _, decision = evaluate(self.config, persisted, self.native.sample(), 100)
        self.assertEqual(decision['reason'], 'feedback_incomplete')
        recovered = undo_feedback(self.native, persisted, self.config)
        self.assertNotIn('feedback_in_flight', recovered['state'])
        self.assertFalse(recovered['state']['enabled'])

    def test_undo_of_confirmation_removes_only_the_new_learning(self):
        result = record_feedback(self.native, self.state, self.config, 'comfortable')
        restored = undo_feedback(self.native, result['state'], self.config)
        self.assertEqual(restored['state']['comfort']['points'], [])
        self.assertEqual(self.native.writes, [])

    def test_old_curve_cannot_receive_comfort_feedback_before_migration(self):
        with self.assertRaises(RuntimeError):
            record_feedback(self.native, self.state, DEFAULT_CONFIG, 'comfortable')
        self.assertFalse(self.state_path.exists())


if __name__ == '__main__':
    unittest.main()
