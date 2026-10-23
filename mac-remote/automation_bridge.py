"""Private adapter to the existing controller workspace, never to bundled state."""
import json
from pathlib import Path
import subprocess
import sys
import os
import fcntl
import time

FIELDS = ('dim_brightness', 'bright_brightness', 'dim_lux', 'bright_lux')


def controller_root():
    location = Path(__file__).with_name('automation-location.json')
    if location.exists():
        return Path(json.loads(location.read_text())['controller_root']).expanduser()
    return Path(__file__).resolve().parent.parent


class Controller:
    def __init__(self, device, root=None):
        self.root = Path(root) if root is not None else controller_root()
        self.device = device
        if not (self.root / 'picture.py').is_file() or not (self.root / 'tv.py').is_file():
            raise RuntimeError('The personal brightness controller could not be found. Rebuild this app from your TV-control project.')

    def invoke(self, action, preferences=None, feedback=None):
        args = [sys.executable, '-B', str(self.root / 'tv.py'), '--device', self.device, 'picture', action]
        if feedback is not None:
            args.append(feedback)
        if preferences is not None:
            if set(preferences) != set(FIELDS):
                raise ValueError('Supply all four brightness preferences.')
            for name in FIELDS:
                args.extend(['--' + name.replace('_', '-'), str(preferences[name])])
        try:
            result = subprocess.run(args, capture_output=True, text=True, timeout=22)
        except subprocess.TimeoutExpired as error:
            raise RuntimeError('Brightness controller timed out. Refresh to check its current state.') from error
        if result.returncode:
            raise RuntimeError(result.stderr.strip() or result.stdout.strip() or 'Brightness controller failed.')
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError as error:
            raise RuntimeError('The brightness controller returned an unreadable response.') from error

    def local(self):
        result = {}
        for name, path in [('config', self.root / 'picture-config.json'),
                           ('state', self.root / 'runtime/picture-state.json')]:
            result[name] = json.loads(path.read_text()) if path.exists() else {}
        return result

    def agent_loaded(self):
        try:
            result = subprocess.run(['launchctl', 'print', f'gui/{os.getuid()}/local.tayo.tv-picture'],
                                    capture_output=True, text=True, timeout=2)
            return result.returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            return False

    def read_record(self, name):
        try:
            return json.loads((self.root / 'runtime' / name).read_text())
        except (OSError, ValueError):
            return None

    def write_record(self, name, value):
        path = self.root / 'runtime' / name
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix('.tmp')
        temporary.write_text(json.dumps(value) + '\n')
        temporary.replace(path)

    def recovery(self, config):
        record = self.read_record('picture-preferences-undo.json')
        current = {name: config.get(name) for name in FIELDS}
        return record['previous'] if record and record.get('applied') == current else None

    def last_check(self):
        # Read a bounded tail; an incomplete final line must not hide the last check.
        try:
            with (self.root / 'runtime/picture-events.jsonl').open('rb') as log:
                log.seek(0, 2)
                log.seek(max(0, log.tell() - 65536))
                lines = log.read().splitlines()
            for line in reversed(lines):
                try:
                    event = json.loads(line)
                    if not event.get('dry_run', False):
                        return event
                except ValueError:
                    continue
        except OSError:
            pass
        return None

    def snapshot(self):
        result = self.local()
        changes = [value for value in (self.read_record('picture-last-change.json'), result['state'].get('feedback_event')) if value]
        return {**result, 'agent_loaded': self.agent_loaded(),
                'undo_preferences': self.recovery(result['config']),
                'last_change': max(changes, key=lambda value: value['time']) if changes else None,
                'last_check': self.last_check()}

    def status(self):
        result = self.local()
        try:
            result.update(self.invoke('status'))
            result['sample_error'] = None
        except RuntimeError as error:
            # Pausing and editing preferences must remain possible when the TV is off.
            result['sample'] = None
            result['sample_error'] = str(error)
        # Re-read local state after the potentially slow TV request.
        result.update(self.snapshot())
        return result

    def perform(self, action, preferences=None):
        if action == 'status':
            return self.status()
        runtime = self.root / 'runtime'
        runtime.mkdir(parents=True, exist_ok=True)
        with (runtime / 'picture-ui.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            return self.change(action, preferences)

    def change(self, action, preferences):
        sample = None
        if action == 'pause':
            self.invoke('disable')
            message = 'Paused. Your current TV brightness is kept. Turn on to resume automatic changes.'
        elif action == 'resume':
            state = self.local()['state']
            self.invoke('resume' if state.get('enabled', False) and self.agent_loaded() else 'enable')
            message = 'Automatic adjustments are on. Only preferences you mark Comfortable are reused. Pause stops further changes.'
        elif action in ('too-bright', 'too-dark', 'comfortable'):
            output = self.invoke('feedback', feedback=action)
            message = output['message']
            sample = output.get('sample')
        elif action == 'undo-feedback':
            output = self.invoke('undo-feedback')
            message = output['message']
            sample = output.get('sample')
        elif action == 'levels':
            config = self.local()['config']
            current = {name: config[name] for name in FIELDS}
            if preferences is None or set(preferences) != set(FIELDS):
                raise ValueError('Supply all four brightness preferences.')
            old_record = self.read_record('picture-preferences-undo.json')
            # Persist recovery before the command: it also works if a timeout hides a successful save.
            if current != preferences:
                self.write_record('picture-preferences-undo.json', {'previous': current, 'applied': preferences})
            try:
                self.invoke('levels', preferences)
            except Exception:
                # A rejected save must not erase an earlier successful save's recovery.
                actual = self.local()['config']
                if all(actual.get(name) == current[name] for name in FIELDS):
                    if old_record is not None:
                        self.write_record('picture-preferences-undo.json', old_record)
                    else:
                        (self.root / 'runtime/picture-preferences-undo.json').unlink(missing_ok=True)
                raise
            message = 'Brightness settings saved. Undo last save restores the previous settings.'
        elif action == 'undo':
            previous = self.recovery(self.local()['config'])
            if previous is None:
                raise RuntimeError('These settings changed since the last save. Refresh to see the current settings before editing again.')
            self.invoke('levels', previous)
            (self.root / 'runtime/picture-preferences-undo.json').unlink(missing_ok=True)
            message = 'Previous brightness settings restored. The on/off state has not changed.'
        else:
            raise ValueError('Unknown automation action.')
        self.write_record('picture-last-change.json', {'time': time.time(), 'message': message})
        return {**self.snapshot(), 'message': message, **({'sample': sample} if sample is not None else {})}
