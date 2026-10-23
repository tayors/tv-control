import subprocess
import unittest
from unittest.mock import Mock, patch

from media_apps import parse_media, parse_apps, launch_app, launcher_apps
from remote_bridge import RemoteTV


def session(package='com.example.video', active=True, state='PLAYING(3)', metadata='A title, A creator, null'):
    return f'''      package={package}
      active={str(active).lower()}
      state=PlaybackState {{state={state}, position=10, speed=1.0}}
      metadata: size=5, description={metadata}
      queueTitle=null
'''


class MediaTests(unittest.TestCase):
    def test_title_creator_and_playback_state(self):
        media = parse_media(session())
        self.assertEqual((media['title'], media['subtitle'], media['state'], media['playing']), ('A title', 'A creator', 'Playing', True))

    def test_old_numeric_state_format(self):
        self.assertEqual(parse_media(session(state='2'))['state'], 'Paused')

    def test_inactive_and_stopped_history_is_ignored(self):
        self.assertIsNone(parse_media(session(active=False)+session(state='STOPPED(1)')))

    def test_primary_media_button_session_wins_over_foreground(self):
        text = 'Media button session is com.example.audio/player (userId=0)\n'+session()+session(package='com.example.audio', state='PAUSED(2)')
        self.assertEqual(parse_media(text, 'com.example.video')['package'], 'com.example.audio')

    def test_without_primary_target_foreground_wins(self):
        self.assertEqual(parse_media(session()+session(package='com.example.other'), 'com.example.other')['package'], 'com.example.other')

    def test_missing_metadata_is_not_invented(self):
        media = parse_media(session().replace('metadata: size=5, description=A title, A creator, null', 'metadata: null'))
        self.assertEqual((media['title'], media['subtitle']), ('', ''))

    def test_null_fields_are_empty(self):
        self.assertEqual(parse_media(session(metadata='null, null, null'))['title'], '')

    def test_title_with_commas_is_preserved(self):
        self.assertEqual(parse_media(session(metadata='One, two, three, Creator, null'))['title'], 'One, two, three')

    def test_buffering_is_not_shown_as_playing(self):
        media = parse_media(session(state='BUFFERING(6)'))
        self.assertEqual((media['state'], media['playing']), ('Buffering', False))

    def test_metadata_failure_does_not_disconnect_working_remote(self):
        tv = RemoteTV('tv.local:5555')
        with patch.object(tv, 'shell', side_effect=['mWakefulness=Awake', 'topResumedActivity=ActivityRecord u0 com.example.video/.Main', subprocess.TimeoutExpired('adb', 5)]):
            self.assertEqual(tv.status()['power'], 'Awake')

    def test_sleeping_tv_does_not_read_media_sessions(self):
        tv = RemoteTV('tv.local:5555')
        with patch.object(tv, 'shell', side_effect=['mWakefulness=Asleep', '']) as shell:
            self.assertIsNone(tv.status()['now_playing'])
            self.assertEqual(shell.call_count, 2)


class AppTests(unittest.TestCase):
    def test_catalog_deduplicates_launchable_components(self):
        apps = parse_apps('2 activities found:\n  com.example.app/.Main\n  com.example.app/.Other\n  com.google.android.youtube.tv/.Main\n')
        self.assertEqual(len(apps), 2)
        self.assertIn({'package': 'com.google.android.youtube.tv', 'name': 'YouTube'}, apps)

    def test_catalog_filters_malformed_or_shell_components(self):
        self.assertEqual(parse_apps('com.example.app/.Main;reboot\nnot-a-package/.Main\ncom.example.app/../../Main'), [])

    def test_refresh_catalog_does_not_launch_or_send_keys(self):
        tv = Mock(); tv.shell.return_value = 'com.example.app/.Main'
        self.assertEqual(len(launcher_apps(tv)), 1)
        tv.key.assert_not_called()
        self.assertEqual(tv.shell.call_args.args[:3], ('cmd', 'package', 'query-activities'))

    def test_launch_uses_only_exact_validated_component(self):
        tv = Mock(); tv.shell.side_effect = ['priority=0\ncom.example.app/.Main', 'Starting: Intent']
        launch_app(tv, 'com.example.app')
        tv.key.assert_called_once_with('wake')
        self.assertEqual(tv.shell.call_args.args, ('am', 'start', '-n', 'com.example.app/.Main'))

    def test_nested_java_activity_is_quoted_for_android_shell(self):
        tv = Mock(); tv.shell.side_effect = ['com.example.app/.Main$Inner', 'Starting: Intent']
        launch_app(tv, 'com.example.app')
        self.assertEqual(tv.shell.call_args.args[-1], "'com.example.app/.Main$Inner'")

    def test_android_start_error_is_not_reported_as_success(self):
        tv = Mock(); tv.shell.side_effect = ['com.example.app/.Main', 'Error type 3\nActivity class does not exist.']
        with self.assertRaisesRegex(RuntimeError, 'could be opened'): launch_app(tv, 'com.example.app')

    def test_injected_package_is_rejected_before_shell(self):
        tv = Mock()
        with self.assertRaises(ValueError): launch_app(tv, 'com.example.app; reboot')
        tv.shell.assert_not_called()

    def test_other_package_or_malformed_resolution_never_launches(self):
        for component in ['com.example.other/.Main', 'com.example.app/.Main;reboot', 'No activity found', 'com.example.app/.One\ncom.example.app/.Two']:
            tv = Mock(); tv.shell.return_value = component
            with self.assertRaisesRegex(RuntimeError, 'No launchable'): launch_app(tv, 'com.example.app')
            tv.key.assert_not_called()
            self.assertEqual(tv.shell.call_count, 1)


if __name__ == '__main__':
    unittest.main()
