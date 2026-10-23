import contextlib
import io
import json
import subprocess
import sys
import unittest
from unittest.mock import patch

import remote_bridge as bridge


class RemoteTransportTests(unittest.TestCase):
    def invoke(self, command):
        with patch.object(sys, 'argv', ['remote_bridge.py', '--device', '192.168.1.44:5555', command]):
            with contextlib.redirect_stdout(io.StringIO()) as output:
                bridge.main()
            return json.loads(output.getvalue())

    def test_status_reads_without_sending_keys_or_launching_apps(self):
        with patch.object(bridge, 'RemoteTV') as factory:
            tv = factory.return_value
            tv.status.return_value = {'power': 'Asleep'}
            tv.shell.return_value = 'tv-serial'
            self.assertEqual(self.invoke('status')['power'], 'Asleep')
            tv.key.assert_not_called()
            tv.watch.assert_not_called()

    def test_play_pause_sends_android_media_toggle(self):
        tv = bridge.TV('192.168.1.44:5555')
        with patch.object(tv, 'shell') as shell:
            tv.key('toggle-playback')
            shell.assert_called_once_with('input', 'keyevent', '85')

    def test_wake_retries_after_adb_timeout(self):
        with patch.object(bridge, 'RemoteTV') as factory, patch.object(bridge, 'wake_packet') as wake, patch.object(bridge.time, 'sleep'):
            tv = factory.return_value
            tv.connect.side_effect = [subprocess.TimeoutExpired('adb', 15), None]
            self.invoke('wake')
            self.assertEqual(tv.connect.call_count, 2)
            tv.key.assert_called_once_with('wake')
            wake.assert_called_once()

    def test_adb_connect_failure_in_stdout_is_reported(self):
        tv = bridge.RemoteTV('192.168.1.44:5555')
        result = subprocess.CompletedProcess([], 0, "failed to connect: No route to host", "")
        with patch.object(bridge.subprocess, 'run', return_value=result):
            with self.assertRaisesRegex(RuntimeError, 'No route to host'):
                tv.run('connect', tv.endpoint)

    def test_connected_transport_is_reused(self):
        tv = bridge.RemoteTV('192.168.1.44:5555')
        with patch.object(tv, 'run', return_value='device') as run:
            tv.connect()
            run.assert_called_once_with('-s', tv.endpoint, 'get-state')

    def test_reconnect_repairs_daemon_only_when_no_other_devices(self):
        with patch.object(bridge, 'RemoteTV') as factory, patch.object(bridge.socket, 'create_connection'):
            tv = factory.return_value
            tv.endpoint = '192.168.1.44:5555'
            tv.connect.side_effect = [RuntimeError('No route to host'), None]
            tv.run.side_effect = ['', 'List of devices attached\n', '', '']
            bridge.reconnect(tv)
            self.assertIn(unittest.mock.call('kill-server'), tv.run.call_args_list)
            self.assertEqual(tv.connect.call_count, 2)

    def test_reconnect_keeps_other_device_sessions(self):
        with patch.object(bridge, 'RemoteTV') as factory, patch.object(bridge.socket, 'create_connection'):
            tv = factory.return_value
            tv.endpoint = '192.168.1.44:5555'
            tv.connect.side_effect = RuntimeError('No route to host')
            tv.run.side_effect = ['', 'List of devices attached\nphone123\tdevice\n']
            with self.assertRaisesRegex(RuntimeError, 'Another device'):
                bridge.reconnect(tv)
            self.assertNotIn(unittest.mock.call('kill-server'), tv.run.call_args_list)

    def test_reconnect_without_existing_transport_still_connects(self):
        with patch.object(bridge, 'RemoteTV') as factory:
            tv = factory.return_value
            tv.endpoint = '192.168.1.44:5555'
            tv.run.side_effect = RuntimeError("error: no such device '192.168.1.44:5555'")
            bridge.reconnect(tv)
            tv.connect.assert_called_once()

    def test_reconnect_does_not_ignore_other_disconnect_errors(self):
        with patch.object(bridge, 'RemoteTV') as factory:
            tv = factory.return_value
            tv.run.side_effect = RuntimeError('ADB server refused connection')
            with self.assertRaisesRegex(RuntimeError, 'refused'):
                bridge.reconnect(tv)
            tv.connect.assert_not_called()

    def test_status_learns_identity_without_discovery_when_saved_address_works(self):
        with patch.object(bridge, 'RemoteTV') as factory, patch('remote_discovery.discovery_candidates') as discover:
            tv = factory.return_value
            tv.shell.return_value = 'tv-serial\n'
            tv.status.return_value = {'endpoint': '192.168.1.44:5555', 'power': 'Asleep'}
            result = bridge.read_status(tv, discover=True, serial='tv-serial')
            self.assertEqual(result['serial'], 'tv-serial')
            discover.assert_not_called()
            tv.key.assert_not_called()
            tv.watch.assert_not_called()

    def test_discovery_returns_verified_changed_endpoint_without_sending_controls(self):
        with patch.object(bridge, 'RemoteTV') as factory, patch('remote_discovery.discovery_candidates', return_value=['192.168.1.70:38421']):
            old, found = unittest.mock.Mock(), factory.return_value
            old.connect.side_effect = RuntimeError('Connection refused')
            found.shell.return_value = 'tv-serial'
            found.status.return_value = {'endpoint': '192.168.1.70:38421', 'power': 'Awake'}
            result = bridge.read_status(old, discover=True, serial='tv-serial')
            self.assertEqual(result['endpoint'], '192.168.1.70:38421')
            self.assertTrue(result['discovered'])
            found.key.assert_not_called()
            found.watch.assert_not_called()

    def test_discovery_rejects_device_with_wrong_real_serial(self):
        with patch.object(bridge, 'RemoteTV') as factory, patch('remote_discovery.discovery_candidates', return_value=['192.168.1.70:38421']):
            old, wrong = unittest.mock.Mock(), factory.return_value
            old.connect.side_effect = RuntimeError('Connection refused')
            wrong.shell.return_value = 'another-device'
            with self.assertRaisesRegex(RuntimeError, 'Couldn’t find this TV'):
                bridge.read_status(old, discover=True, serial='tv-serial')
            wrong.status.assert_not_called()
            wrong.key.assert_not_called()

    def test_reassigned_saved_address_is_rejected_before_status(self):
        with patch.object(bridge, 'RemoteTV') as factory:
            tv = factory.return_value
            tv.shell.return_value = 'another-device'
            with self.assertRaisesRegex(RuntimeError, 'different device'):
                bridge.read_status(tv, serial='tv-serial')
            tv.status.assert_not_called()

    def test_identity_falls_back_to_boot_serial(self):
        with patch.object(bridge, 'RemoteTV') as factory:
            tv = factory.return_value
            tv.shell.side_effect = ['unknown', 'boot-serial']
            tv.status.return_value = {'power': 'Asleep'}
            self.assertEqual(bridge.checked_status(tv, 'boot-serial')['serial'], 'boot-serial')

    def test_expired_status_budget_stops_adb_before_launch(self):
        tv = bridge.RemoteTV('192.168.1.44:5555')
        tv.deadline = 0
        with patch.object(bridge.subprocess, 'run') as run:
            with self.assertRaisesRegex(RuntimeError, 'timed out'):
                tv.run('devices')
            run.assert_not_called()

    def test_wake_packet_format(self):
        with patch.object(bridge.socket, 'socket') as factory:
            connection = factory.return_value.__enter__.return_value
            bridge.wake_packet('3c:c5:dd:1f:c6:a6', '192.168.1.255')
            packet = b'\xff' * 6 + bytes.fromhex('3cc5dd1fc6a6') * 16
            self.assertEqual(connection.sendto.call_args_list[0].args, (packet, ('192.168.1.255', 9)))
            self.assertEqual(connection.sendto.call_args_list[1].args, (packet, ('192.168.1.255', 7)))


if __name__ == '__main__':
    unittest.main()
