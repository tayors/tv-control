#!/usr/bin/env python3
"""Local ADB remote for the living-room TV. Uses Python's standard library."""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys

APPS = {
    "youtube": "com.google.android.youtube.tv",
    "prime": "com.amazon.amazonvideo.livingroom",
    "netflix": "com.netflix.ninja",
    "disney": "com.disney.disneyplus",
    "plex": "com.plexapp.android",
    "music": "com.google.android.youtube.tvmusic",
}
KEYS = {
    "wake": 224, "sleep": 223, "home": 3, "back": 4,
    "up": 19, "down": 20, "left": 21, "right": 22, "select": 23,
    "play": 126, "pause": 127, "volume-up": 24, "volume-down": 25,
    "mute": 164,
}


class TV:
    def __init__(self, endpoint):
        self.endpoint = endpoint
        self.adb = shutil.which("adb") or "/opt/homebrew/bin/adb"

    def run(self, *args):
        result = subprocess.run(
            [self.adb, *args], capture_output=True, text=True, timeout=15
        )
        if result.returncode:
            raise RuntimeError(result.stderr.strip() or result.stdout.strip())
        return result.stdout.strip()

    def connect(self):
        self.run("connect", self.endpoint)
        if self.run("-s", self.endpoint, "get-state") != "device":
            raise RuntimeError("TV is unavailable or requires ADB authorization.")

    def shell(self, *args):
        return self.run("-s", self.endpoint, "shell", *args)

    def key(self, name):
        self.shell("input", "keyevent", str(KEYS[name]))

    def status(self):
        power = self.shell("dumpsys", "power")
        activity = self.shell("dumpsys", "activity", "activities")
        sensors = self.shell("dumpsys", "sensorservice")
        awake = re.search(r"mWakefulness=(\w+)", power)
        foreground = re.search(r"topResumedActivity=.*? u\d+ ([^ /}]+)/", activity)
        events = re.findall(r"wall=[^\n]+\)\s+([\d.]+),", sensors)
        return {
            "endpoint": self.endpoint,
            "power": awake.group(1) if awake else "unknown",
            "foreground_app": foreground.group(1) if foreground else None,
            "latest_reported_lux": float(events[-1]) if events else None,
        }

    def watch(self, app):
        package = APPS[app]
        resolved = self.shell(
            "cmd", "package", "resolve-activity", "--brief",
            "-a", "android.intent.action.MAIN",
            "-c", "android.intent.category.LEANBACK_LAUNCHER", package,
        )
        components = [line.strip() for line in resolved.splitlines()
                      if line.strip().startswith(package + "/")]
        if len(components) != 1:
            raise RuntimeError(f"No launchable TV activity found for {app}.")
        self.key("wake")
        return self.shell("am", "start", "-n", components[0])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device", default=os.environ.get("TV_ADB_DEVICE", "192.168.1.44:5555"))
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("status", help="Read power, current app and latest sensor lux")
    sub.add_parser("apps", help="List app shortcuts without connecting")
    watch = sub.add_parser("watch", help="Wake the TV and open an app")
    watch.add_argument("app", choices=APPS)
    picture = sub.add_parser("picture", help="Control brightness from the ambient light sensor")
    actions = picture.add_subparsers(dest="picture_action")
    for action in ["status", "enable", "disable", "resume", "preview", "tick", "restore", "learn", "undo-feedback"]:
        actions.add_parser(action)
    feedback = actions.add_parser('feedback')
    feedback.add_argument('feedback', choices=['too-bright', 'too-dark', 'comfortable'])
    levels = actions.add_parser("levels")
    levels.add_argument("--dim-brightness", type=int)
    levels.add_argument("--bright-brightness", type=int)
    levels.add_argument("--dim-lux", type=float)
    levels.add_argument("--bright-lux", type=float)
    for name in KEYS:
        sub.add_parser(name, help=f"Send {name} to the TV")
    args = parser.parse_args()
    if args.command == "apps":
        print(json.dumps(APPS, indent=2))
        return
    tv = TV(args.device)
    if args.command == "picture":
        from picture import run
        run(tv, args)
        return
    tv.connect()
    if args.command in (None, "status"):
        print(json.dumps(tv.status(), indent=2))
    elif args.command == "watch":
        print(tv.watch(args.app))
    else:
        tv.key(args.command)
        print(f"Sent {args.command}.")


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, ValueError, OSError, subprocess.TimeoutExpired) as error:
        print(f"TV control failed: {error}", file=sys.stderr)
        sys.exit(1)
