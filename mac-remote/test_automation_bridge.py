import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from automation_bridge import Controller
from sensor_policy import DEFAULT_CONFIG

SOURCE = Path(__file__).resolve().parent.parent


class AutomationBridgeTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        for name in ['tv.py', 'picture.py', 'sensor_policy.py', 'comfort_policy.py']:
            shutil.copy2(SOURCE / name, self.root / name)
        (self.root / 'picture-config.json').write_text(json.dumps({**DEFAULT_CONFIG, 'poll_interval_seconds': 10}))
        (self.root / 'runtime').mkdir()
        self.state = self.root / 'runtime/picture-state.json'
        self.state.write_text(json.dumps({'enabled': False, 'last_expected': 29}))
        self.controller = Controller('192.0.2.10:5555', self.root)

    def test_status_reads_shared_controller_and_never_mutates_it(self):
        before = self.state.read_bytes()
        with patch.object(self.controller, 'invoke', return_value={'sample': {'awake': True, 'backlight': 29}}) as invoke, patch.object(self.controller, 'agent_loaded', return_value=True):
            result = self.controller.status()
        invoke.assert_called_once_with('status')
        self.assertFalse(result['state']['enabled'])
        self.assertEqual(result['sample']['backlight'], 29)
        self.assertEqual(before, self.state.read_bytes())

    def test_offline_status_still_exposes_pause_state_and_preferences(self):
        with patch.object(self.controller, 'invoke', side_effect=RuntimeError('TV unreachable')), patch.object(self.controller, 'agent_loaded', return_value=False):
            result = self.controller.status()
        self.assertIsNone(result['sample'])
        self.assertFalse(result['state']['enabled'])
        self.assertEqual(result['config'], self.controller.local()['config'])
        self.assertEqual(result['sample_error'], 'TV unreachable')

    def test_preferences_save_to_workspace_without_enabling_or_touching_tv(self):
        preferences = {'dim_brightness': 29, 'bright_brightness': 50, 'dim_lux': 10, 'bright_lux': 150}
        before = self.state.read_bytes()
        self.controller.invoke('levels', preferences)
        config = json.loads((self.root / 'picture-config.json').read_text())
        for field, value in preferences.items():
            self.assertEqual(config[field], value)
        self.assertEqual(before, self.state.read_bytes())

    def test_invalid_preferences_do_not_partially_save(self):
        config = self.root / 'picture-config.json'
        before = config.read_bytes()
        with self.assertRaises(RuntimeError):
            self.controller.invoke('levels', {'dim_brightness': 60, 'bright_brightness': 30, 'dim_lux': 10, 'bright_lux': 150})
        self.assertEqual(before, config.read_bytes())
        self.assertFalse(json.loads(self.state.read_text())['enabled'])

    def test_pause_is_sent_before_attempting_live_status(self):
        with patch.object(self.controller, 'invoke', return_value={}) as invoke, patch.object(self.controller, 'agent_loaded', return_value=False):
            self.controller.perform('pause')
        invoke.assert_called_once_with('disable')

    def test_resume_enables_disabled_controller_or_clears_manual_hold(self):
        with patch.object(self.controller, 'invoke', return_value={}) as invoke, patch.object(self.controller, 'agent_loaded', return_value=True):
            self.controller.perform('resume')
            invoke.assert_called_once_with('enable')
            invoke.reset_mock()
            self.state.write_text(json.dumps({'enabled': True, 'hold_until': 9999999999}))
            self.controller.perform('resume')
            invoke.assert_called_once_with('resume')

    def test_saved_settings_can_be_undone_after_app_restart_without_changing_state(self):
        before = self.controller.local()['config']
        self.state.write_text(json.dumps({'enabled': True, 'hold_until': 9999999999}))
        state_before = self.state.read_bytes()
        preferences = {'dim_brightness': 29, 'bright_brightness': 50, 'dim_lux': 10, 'bright_lux': 150}
        with patch.object(self.controller, 'agent_loaded', return_value=False):
            saved = self.controller.perform('levels', preferences)
        self.assertEqual(saved['undo_preferences']['dim_brightness'], before['dim_brightness'])
        restarted = Controller('192.0.2.10:5555', self.root)
        with patch.object(restarted, 'agent_loaded', return_value=False):
            restored = restarted.perform('undo')
        self.assertEqual(restored['config'], before)
        self.assertIsNone(restored['undo_preferences'])
        self.assertEqual(state_before, self.state.read_bytes())
        self.assertIn('restored', restored['last_change']['message'])

    def test_undo_never_overwrites_settings_changed_elsewhere(self):
        preferences = {'dim_brightness': 29, 'bright_brightness': 50, 'dim_lux': 10, 'bright_lux': 150}
        with patch.object(self.controller, 'agent_loaded', return_value=False):
            self.controller.perform('levels', preferences)
        self.controller.invoke('levels', {**preferences, 'dim_brightness': 31})
        with self.assertRaisesRegex(RuntimeError, 'changed since'):
            self.controller.perform('undo')
        self.assertEqual(self.controller.local()['config']['dim_brightness'], 31)

    def test_failed_save_preserves_existing_undo(self):
        preferences = {'dim_brightness': 29, 'bright_brightness': 50, 'dim_lux': 10, 'bright_lux': 150}
        with patch.object(self.controller, 'agent_loaded', return_value=False):
            saved = self.controller.perform('levels', preferences)
            with self.assertRaises(RuntimeError):
                self.controller.perform('levels', {**preferences, 'dim_brightness': 70})
        self.assertEqual(self.controller.recovery(self.controller.local()['config']), saved['undo_preferences'])

    def test_timeout_after_successful_save_keeps_recovery(self):
        preferences = {'dim_brightness': 29, 'bright_brightness': 50, 'dim_lux': 10, 'bright_lux': 150}
        before = self.controller.local()['config']
        invoke = self.controller.invoke
        def timed_out(action, values):
            invoke(action, values)
            raise RuntimeError('Timed out after applying')
        with patch.object(self.controller, 'invoke', side_effect=timed_out):
            with self.assertRaises(RuntimeError):
                self.controller.perform('levels', preferences)
        self.assertEqual(self.controller.recovery(self.controller.local()['config'])['dim_brightness'], before['dim_brightness'])

    def test_last_check_tolerates_incomplete_log_and_ignores_preview(self):
        (self.root / 'runtime/picture-events.jsonl').write_text(
            json.dumps({'time': 1, 'reason': 'deadband', 'curve_target': 40}) + '\n' +
            json.dumps({'time': 2, 'dry_run': True, 'curve_target': 50}) + '\n{"time":')
        self.assertEqual(self.controller.last_check()['curve_target'], 40)

    def test_learning_migration_is_offline_and_preserves_enabled_state_and_old_preferences(self):
        config_before = self.controller.local()['config']
        self.state.write_text(json.dumps({'enabled': True, 'last_expected': 40}))
        self.controller.invoke('learn')  # TEST-NET endpoint cannot be connected to; this must stay local.
        migrated = self.controller.local()
        self.assertEqual(migrated['config']['strategy'], 'learned')
        for key, value in config_before.items():
            self.assertEqual(migrated['config'][key], value)
        self.assertTrue(migrated['state']['enabled'])
        self.assertEqual(migrated['state']['last_expected'], 40)
        self.assertNotIn('comfort', migrated['state'])
        backup = self.root / 'runtime/picture-before-learning.json'
        self.assertEqual(json.loads(backup.read_text()), config_before)
        self.controller.invoke('learn')
        self.assertEqual(json.loads(backup.read_text()), config_before)

    def test_feedback_routes_only_explicit_choice_to_controller(self):
        with patch.object(self.controller, 'invoke', return_value={'message': 'Remembered.', 'sample': {'awake': True}}) as invoke, patch.object(self.controller, 'agent_loaded', return_value=True):
            result = self.controller.perform('comfortable')
        invoke.assert_called_once_with('feedback', feedback='comfortable')
        self.assertEqual(result['message'], 'Remembered.')
        self.assertEqual(result['sample'], {'awake': True})

    def test_persisted_feedback_receipt_survives_adapter_timeout(self):
        self.state.write_text(json.dumps({'enabled': True, 'feedback_event': {'time': 200, 'message': 'Remembered.'}}))
        self.controller.write_record('picture-last-change.json', {'time': 100, 'message': 'Older action'})
        with patch.object(self.controller, 'agent_loaded', return_value=True):
            self.assertEqual(self.controller.snapshot()['last_change']['message'], 'Remembered.')


if __name__ == '__main__':
    unittest.main()
