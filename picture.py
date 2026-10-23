"""Sensor-driven TCL brightness baselines, using the TV's verified native API."""
import copy
import fcntl
import json
import os
from pathlib import Path
import plistlib
import re
import subprocess
import sys
import time
import uuid

from sensor_policy import DEFAULT_CONFIG as POLICY_DEFAULT_CONFIG, evaluate, validate_config
from comfort_policy import plan_feedback

ROOT = Path(__file__).resolve().parent
RUNTIME = ROOT / 'runtime'
CONFIG = ROOT / 'picture-config.json'
STATE = RUNTIME / 'picture-state.json'
LABEL = 'local.tayo.tv-picture'
AGENT = Path.home() / 'Library/LaunchAgents' / (LABEL + '.plist')
SDK = '/system_ext/framework/com.tcl.tv.display.jar'
SDK_SHA256 = 'c14f5ea2d1374ab5a6abeae0c6bbfa15a6a0129a12aad7908332c62fc44a4600'
DEFAULT_CONFIG = {
    **POLICY_DEFAULT_CONFIG, 'poll_interval_seconds': 10,
}


def read_json(path, default):
    return json.loads(path.read_text()) if path.exists() else copy.deepcopy(default)


def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(data, indent=2) + '\n')
    temporary.replace(path)


class NativePicture:
    def __init__(self, tv):
        self.tv = tv
        self.verified = False

    def verify(self):
        if not self.verified:
            digest = self.tv.shell('sha256sum', SDK).split()[0]
            if digest != SDK_SHA256:
                raise RuntimeError('TCL SDK changed: native transactions require revalidation.')
            self.verified = True

    def call(self, transaction, *values):
        self.verify()
        args = ['service', 'call', 'tcl_tv_display', str(transaction)]
        for value in values:
            args.extend(['i32', str(value)])
        result = self.tv.shell(*args)
        words = re.findall(r'\b[0-9a-f]{8}\b', result.split("'")[0])
        if len(words) != 2 or words[0] != '00000000':
            raise RuntimeError('Unexpected TCL Binder response: ' + result)
        value = int(words[1], 16)
        return value - 2**32 if value >= 2**31 else value

    def context(self):
        return [self.call(27), self.call(172)]

    def sample(self):
        power = self.tv.shell('dumpsys', 'power')
        awake = re.search(r'mWakefulness=(\w+)', power)
        if not awake or awake.group(1) != 'Awake':
            return {'awake': False}
        context = self.context()
        backlight = self.call(101)
        adaptive = self.call(107)
        sensors = self.tv.shell('dumpsys', 'sensorservice')
        uptime = float(self.tv.shell('cat', '/proc/uptime').split()[0])
        events = re.findall(r'\(ts=([\d.]+), wall=[^)]*\)\s+([\d.]+),', sensors)
        lux = age = None
        if events:
            timestamp, reading = map(float, events[-1])
            if uptime >= timestamp - 1:
                lux, age = reading, max(0, uptime - timestamp)
        if self.context() != context:
            raise RuntimeError('Picture context changed during sample; retry on the next reading.')
        if not 0 <= backlight <= 100:
            raise RuntimeError('Invalid native backlight readback.')
        return {
            'awake': True, 'lux': lux, 'sensor_age_seconds': age,
            'picture_mode': context[0], 'hdr_setting': context[1],
            'backlight': backlight, 'adaptive_brightness': adaptive,
        }

    def set_backlight(self, target, context):
        if type(target) is not int or not 5 <= target <= 85:
            raise ValueError('Automation brightness must be an integer from 5 to 85.')
        if self.context() != context or context[0] != 3:
            raise RuntimeError('Picture context is outside the verified Movie preset.')
        before = self.call(101)
        if before > 85:
            raise RuntimeError('Preserving this high-brightness picture context.')
        # SDK evidence: apply CURRENT=0, action EXEC_SAVE=2. Only current context.
        if self.call(100, 0, target, 2) != 1:
            raise RuntimeError('TCL rejected the backlight change.')
        try:
            stable = 0
            for _ in range(15):
                time.sleep(0.3)
                if self.context() != context:
                    raise RuntimeError('Picture context changed during the write.')
                stable = stable + 1 if self.call(101) == target else 0
                if stable >= 2:
                    return
            raise RuntimeError('Native brightness did not settle at the requested value.')
        except BaseException:
            # Restore only if the same preset is still active.
            if self.context() == context:
                self.call(100, 0, before, 2)
            raise


def load_config():
    config = read_json(CONFIG, DEFAULT_CONFIG)
    validate_config(config)
    interval = config.get('poll_interval_seconds', 10)
    if type(interval) is not int or not 5 <= interval <= 300:
        raise ValueError('Sensor polling interval must be 5–300 seconds.')
    return config


def tick(tv, state, config, dry_run=False):
    native = NativePicture(tv)
    sample = native.sample()
    if not state.get('enabled', False) and not dry_run:
        return state, {'action': 'skip', 'reason': 'disabled', 'sample': sample}
    updated, decision = evaluate(config, state, sample, time.time())
    if decision['action'] == 'apply' and not dry_run:
        context = [sample['picture_mode'], sample['hdr_setting']]
        baselines = updated.setdefault('baselines', {})
        baselines.setdefault(str(context), sample['backlight'])
        save_json(STATE, updated)
        try:
            native.set_backlight(decision['target'], context)
        except BaseException:
            updated['enabled'] = False
            save_json(STATE, updated)
            raise
        updated['last_expected'] = decision['target']
    return updated, {**decision, 'sample': sample, 'dry_run': dry_run}


def feedback_sample(native, config):
    sample = native.sample()
    _, decision = evaluate({**config, 'strategy': 'learned'}, {}, sample, time.time())
    reason = decision.get('reason')
    if reason != 'unlearned_light' or sample.get('backlight', 0) < 5:
        messages = {
            'tv_off': 'Turn on the TV before giving picture feedback.',
            'unsupported_picture_mode': 'Feedback currently supports the TV’s Movie picture mode. Switch to Movie mode, then refresh.',
            'adaptive_brightness_off': 'Turn on Adaptive Brightness in the TV settings so its light sensor is available.',
            'high_backlight': 'This high-brightness picture setting is outside the supported adjustment range.',
        }
        raise RuntimeError(messages.get(reason, 'A fresh light-sensor and picture reading is needed. Refresh, then try again.'))
    return sample


def record_feedback(native, state, config, kind):
    if config.get('strategy') != 'learned':
        raise RuntimeError('Enable comfort learning before giving feedback.')
    if state.get('feedback_in_flight'):
        raise RuntimeError('The previous picture change was not confirmed. Undo last feedback before trying again.')
    sample = feedback_sample(native, config)
    now = time.time()
    previous = copy.deepcopy(state.get('comfort', {'points': []}))
    memory, target, message = plan_feedback(previous, sample, kind, now, uuid.uuid4().hex)
    updated = copy.deepcopy(state)
    context = [sample['picture_mode'], sample['hdr_setting']]
    updated.update(comfort=memory, hold_until=0, last_expected=target, lux_samples=[])
    updated['feedback_undo'] = {'comfort': previous, 'before': sample['backlight'], 'after': target,
                                'context': context, 'revision': memory['revision'], 'time': now}
    if target != sample['backlight']:
        updated.setdefault('baselines', {}).setdefault(str(context), sample['backlight'])
        # Persist a recovery record before a TV write. Interrupted work blocks all further automation.
        updated['feedback_in_flight'] = True
        save_json(STATE, updated)
        try:
            native.set_backlight(target, context)
        except BaseException:
            updated['enabled'] = False
            save_json(STATE, updated)
            raise
        updated.pop('feedback_in_flight', None)
    updated['feedback_event'] = {'time': now, 'message': message, 'kind': kind}
    save_json(STATE, updated)
    return {'message': message, 'state': updated, 'sample': {**sample, 'backlight': target}}


def undo_feedback(native, state, config):
    undo = state.get('feedback_undo')
    if not undo or undo.get('revision') != state.get('comfort', {}).get('revision'):
        raise RuntimeError('There is no current feedback to undo. Refresh to see the latest state.')
    sample = native.sample()
    context = [sample.get('picture_mode'), sample.get('hdr_setting')]
    restore = (sample.get('awake') and context == undo['context'] and
               sample.get('backlight') == undo['after'] and undo['before'] != undo['after'])
    updated = copy.deepcopy(state)
    if restore:
        updated['feedback_in_flight'] = True
        save_json(STATE, updated)
        try:
            native.set_backlight(undo['before'], context)
        except BaseException:
            updated['enabled'] = False
            save_json(STATE, updated)
            raise
    changed_elsewhere = sample.get('awake') and (context != undo['context'] or sample.get('backlight') != undo['after'])
    hold = max(state.get('hold_until', 0), time.time() + config['manual_hold_seconds']) if changed_elsewhere else state.get('hold_until', 0)
    updated.update(comfort=undo['comfort'], last_expected=undo['before'] if restore else sample.get('backlight'),
                   hold_until=hold, lux_samples=[])
    updated.pop('feedback_undo', None)
    updated.pop('feedback_in_flight', None)
    message = ('Last feedback undone. The previous picture brightness was restored.' if restore else
               'Last feedback undone. The current TV brightness was left alone.')
    if changed_elsewhere:
        message += ' Your newer picture setting takes priority for one hour.'
    updated['feedback_event'] = {'time': time.time(), 'message': message, 'kind': 'undo'}
    save_json(STATE, updated)
    return {'message': message, 'state': updated, 'sample': {**sample, **({'backlight': undo['before']} if restore else {})}}


def configure_agent(tv, config):
    AGENT.parent.mkdir(parents=True, exist_ok=True)
    job = {
        'Label': LABEL,
        'ProgramArguments': [sys.executable, str(ROOT / 'tv.py'), '--device',
                             tv.endpoint, 'picture', 'tick'],
        'WorkingDirectory': str(ROOT),
        'StartInterval': config['poll_interval_seconds'], 'RunAtLoad': True,
        'StandardOutPath': str(RUNTIME / 'launchd.stdout.log'),
        'StandardErrorPath': str(RUNTIME / 'launchd.stderr.log'),
    }
    domain = f'gui/{os.getuid()}'
    subprocess.run(['launchctl', 'bootout', domain + '/' + LABEL], capture_output=True)
    AGENT.write_bytes(plistlib.dumps(job))
    result = subprocess.run(['launchctl', 'bootstrap', domain, str(AGENT)],
                            capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError('Could not start sensor controller: ' + result.stderr.strip())


def run(tv, args):
    RUNTIME.mkdir(parents=True, exist_ok=True)
    with (RUNTIME / 'picture.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        config = load_config()
        state = read_json(STATE, {'enabled': False})
        action = args.picture_action or 'status'
        output = {}
        if action == 'tick' and not state.get('enabled', False):
            return
        if action not in ('disable', 'resume', 'levels', 'learn'):
            tv.connect()
        if action == 'status':
            output = {'config': config, 'state': state, 'sample': NativePicture(tv).sample()}
        elif action == 'enable':
            NativePicture(tv).verify()
            save_json(CONFIG, config)
            state.update(enabled=True, hold_until=0, last_expected=None)
            save_json(STATE, state)
            try:
                configure_agent(tv, config)
            except BaseException:
                state['enabled'] = False
                save_json(STATE, state)
                raise
            output = {'enabled': True, 'poll_interval_seconds': config['poll_interval_seconds']}
        elif action == 'disable':
            state['enabled'] = False
            save_json(STATE, state)
            subprocess.run(['launchctl', 'bootout', f'gui/{os.getuid()}/{LABEL}'],
                           capture_output=True)
            output = {'enabled': False, 'brightness': 'kept at current value'}
        elif action == 'resume':
            state.update(hold_until=0, last_expected=None, lux_samples=[])
            save_json(STATE, state)
            output = {'manual_hold_cleared': True, 'enabled': state.get('enabled', False)}
        elif action == 'levels':
            for key in ['dim_brightness', 'bright_brightness', 'dim_lux', 'bright_lux']:
                value = getattr(args, key, None)
                if value is not None:
                    config[key] = value
            validate_config(config)
            save_json(CONFIG, config)
            output = {'config': config}
        elif action == 'learn':
            if config.get('strategy') != 'learned':
                save_json(RUNTIME / 'picture-before-learning.json', config)
                config['strategy'] = 'learned'
                save_json(CONFIG, config)
                state['feedback_event'] = {'time': time.time(), 'message': 'Comfort learning is ready. Tell me how the picture feels to teach your first preference.', 'kind': 'setup'}
                save_json(STATE, state)
            output = {'strategy': 'learned', 'message': 'Comfort learning is ready. No picture changes occur until you give feedback.'}
        elif action == 'feedback':
            output = record_feedback(NativePicture(tv), state, config, args.feedback)
        elif action == 'undo-feedback':
            output = undo_feedback(NativePicture(tv), state, config)
        elif action in ('tick', 'preview'):
            dry_run = action == 'preview'
            updated, output = tick(tv, state, config, dry_run)
            if not dry_run:
                save_json(STATE, updated)
                log_path = RUNTIME / 'picture-events.jsonl'
                if log_path.exists() and log_path.stat().st_size > 2_000_000:
                    log_path.replace(RUNTIME / 'picture-events.previous.jsonl')
                with log_path.open('a') as log:
                    log.write(json.dumps({'time': time.time(), **output}) + '\n')
        elif action == 'restore':
            if state.get('enabled'):
                raise RuntimeError('Disable the sensor controller before restoring the baseline.')
            native = NativePicture(tv)
            context = native.context()
            baseline = state.get('baselines', {}).get(str(context))
            if baseline is None:
                raise RuntimeError('No baseline saved for this picture context.')
            native.set_backlight(baseline, context)
            state['last_expected'] = None
            save_json(STATE, state)
            output = {'restored': baseline, 'context': context}
        if action != 'tick':
            print(json.dumps(output, indent=2))
