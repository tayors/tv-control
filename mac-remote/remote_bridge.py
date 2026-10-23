"""Bounded ADB transport for the native menu-bar remote."""
import argparse
import ipaddress
import json
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys
import time

# Also support running directly from the source checkout.
if not (Path(__file__).parent / 'tv.py').exists():
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tv import TV, APPS, KEYS

KEYS['toggle-playback'] = 85
APPS.update({'stremio': 'com.stremio.one', 'apple': 'com.apple.atve.androidtv.appletv'})


class RemoteTV(TV):
    deadline = None

    def __init__(self, endpoint):
        super().__init__(endpoint)
        self.adb = shutil.which('adb') or next((path for path in ('/opt/homebrew/bin/adb', '/usr/local/bin/adb') if Path(path).is_file()), '/opt/homebrew/bin/adb')

    def run(self, *args):
        remaining = self.deadline - time.monotonic() if self.deadline is not None else 5
        if remaining <= 0:
            raise RuntimeError('TV connection timed out. Try Reconnect.')
        result = subprocess.run([self.adb, *args], capture_output=True, text=True, timeout=min(5, remaining))
        output = result.stdout.strip()
        if result.returncode or output.lower().startswith(('failed to connect', 'cannot connect', 'unable to connect')):
            raise RuntimeError(result.stderr.strip() or output)
        return output

    def connect(self):
        # Reuse the live transport; reconnect only when needed.
        try:
            if self.run('-s', self.endpoint, 'get-state') == 'device':
                return
        except (RuntimeError, subprocess.TimeoutExpired):
            pass
        super().connect()

    def status(self):
        # A remote only needs power and the current app, not a sensor dump.
        power = self.shell('dumpsys', 'power')
        activity = self.shell('dumpsys', 'activity', 'activities')
        awake = re.search(r'mWakefulness=(\w+)', power)
        foreground = re.search(r'topResumedActivity=.*? u\d+ ([^ /}]+)/', activity)
        result = {'endpoint': self.endpoint, 'power': awake.group(1) if awake else 'unknown',
                  'foreground_app': foreground.group(1) if foreground else None, 'now_playing': None}
        if result['power'] == 'Awake':
            try:
                from media_apps import parse_media
                result['now_playing'] = parse_media(self.shell('dumpsys', 'media_session'), result['foreground_app'])
            except (RuntimeError, OSError, subprocess.TimeoutExpired):
                pass
        return result


def wake_packet(mac, broadcast):
    octets = bytes.fromhex(mac.replace(':', '').replace('-', ''))
    if len(octets) != 6:
        raise ValueError('Wake address must contain six hexadecimal octets.')
    ipaddress.IPv4Address(broadcast)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as connection:
        connection.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        for port in (9, 7):
            connection.sendto(b'\xff' * 6 + octets * 16, (broadcast, port))


def reconnect(tv):
    """Reset this TV transport; repair a broken daemon only if it has no devices."""
    try:
        tv.run('disconnect', tv.endpoint)
    except RuntimeError as error:
        # A missing old transport is precisely when reconnect is useful.
        if not any(message in str(error).lower() for message in ('no such device', 'not connected')):
            raise
    try:
        tv.connect()
    except RuntimeError as error:
        if 'No route to host' not in str(error):
            raise
        host, port = tv.endpoint.rsplit(':', 1)
        # Only repair if the TV is actually reachable and no other device uses ADB.
        with socket.create_connection((host, int(port)), timeout=2):
            pass
        if any(line.strip() for line in tv.run('devices').splitlines()[1:]):
            raise RuntimeError('ADB cannot reach this TV. Another device is using ADB; restart ADB after finishing that session.') from error
        tv.run('kill-server')
        tv.run('start-server')
        tv.connect()


def checked_status(tv, expected_serial=''):
    serial = tv.shell('getprop', 'ro.serialno').strip()
    if serial.lower() in ('', 'unknown', 'null'):
        serial = tv.shell('getprop', 'ro.boot.serialno').strip()
    if serial.lower() in ('', 'unknown', 'null'):
        serial = ''
    if expected_serial and serial != expected_serial:
        raise RuntimeError('The saved address belongs to a different device. Looking for your TV requires local-network discovery.')
    return {**tv.status(), 'serial': serial}


def read_status(tv, *, reset=False, discover=False, mac='', serial=''):
    # One overall budget covers initial connection, discovery and identity checks.
    deadline = time.monotonic() + 22
    tv.deadline = deadline
    try:
        if reset:
            reconnect(tv)
        else:
            tv.connect()
        return checked_status(tv, serial)
    except (RuntimeError, OSError, subprocess.TimeoutExpired) as original:
        if not discover:
            raise
        from remote_discovery import discovery_candidates
        for endpoint in discovery_candidates(tv, mac, serial, deadline):
            if time.monotonic() >= deadline:
                break
            candidate = RemoteTV(endpoint)
            candidate.deadline = deadline
            try:
                candidate.connect()
                result = checked_status(candidate, serial)
                return {**result, 'discovered': True}
            except (RuntimeError, OSError, subprocess.TimeoutExpired):
                continue
        raise RuntimeError(str(original) + '\nCouldn’t find this TV on the current local network. Turn on the TV, check debugging, then Reconnect.') from original


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--device', required=True)
    parser.add_argument('--mac', default='3c:c5:dd:1f:c6:a6')
    parser.add_argument('--broadcast', default='192.168.1.255')
    parser.add_argument('--discover', action='store_true')
    parser.add_argument('--serial', default='')
    parser.add_argument('--package', default='')
    for field, field_type in [('dim-brightness', int), ('bright-brightness', int), ('dim-lux', float), ('bright-lux', float)]:
        parser.add_argument('--' + field, type=field_type)
    parser.add_argument('command', choices=['status', 'reconnect', 'apps', 'launch-app', 'automation-status', 'automation-pause', 'automation-resume', 'automation-levels', 'automation-undo', 'automation-too-bright', 'automation-too-dark', 'automation-comfortable', 'automation-undo-feedback', *KEYS, *APPS])
    args = parser.parse_args()
    if args.command.startswith('automation-'):
        from automation_bridge import Controller, FIELDS
        action = args.command.removeprefix('automation-')
        preferences = {field: getattr(args, field) for field in FIELDS} if action == 'levels' else None
        print(json.dumps(Controller(args.device).perform(action, preferences)))
        return
    tv = RemoteTV(args.device)
    if args.command == 'wake':
        wake_packet(args.mac, args.broadcast)
        last_error = 'TV has not responded yet.'
        for attempt in range(3):
            try:
                tv.connect()
                tv.key('wake')
                print(json.dumps({'message': 'TV responded to wake.'}))
                return
            except (RuntimeError, OSError, TimeoutError, subprocess.TimeoutExpired) as error:
                last_error = str(error)
                if attempt < 2:
                    time.sleep(1)
        raise RuntimeError('Wake signal sent. TV has not connected yet; it may still turn on. ' + last_error)
    if args.command in ('status', 'reconnect'):
        print(json.dumps(read_status(tv, reset=args.command == 'reconnect', discover=args.discover, mac=args.mac, serial=args.serial)))
        return
    tv.connect()
    if args.command == 'apps':
        from media_apps import launcher_apps
        print(json.dumps({'apps': launcher_apps(tv)}))
    elif args.command == 'launch-app':
        from media_apps import launch_app
        launch_app(tv, args.package)
        print(json.dumps({'message': 'Opened app'}))
    elif args.command in APPS:
        tv.watch(args.command)
        print(json.dumps({'message': 'Opened ' + args.command.capitalize()}))
    else:
        tv.key(args.command)
        print(json.dumps({'message': 'Sent ' + args.command.replace('-', ' ')}))


if __name__ == '__main__':
    try:
        main()
    except subprocess.TimeoutExpired:
        print('TV connection timed out. Check its network connection and ADB debugging, then Reconnect.', file=sys.stderr)
        sys.exit(1)
    except Exception as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
