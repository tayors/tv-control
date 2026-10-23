"""Read-only media/session parsing and validated TV launcher shortcuts."""
import re
import shlex

PACKAGE = r'[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z0-9_]+)+'
NAMES = {
    'com.google.android.youtube.tv': 'YouTube', 'com.stremio.one': 'Stremio',
    'com.netflix.ninja': 'Netflix', 'com.amazon.amazonvideo.livingroom': 'Prime Video',
    'com.disney.disneyplus': 'Disney+', 'com.apple.atve.androidtv.appletv': 'Apple TV',
    'com.crunchyroll.crunchyroid': 'Crunchyroll', 'com.dstvmobile.android': 'DStv',
    'com.plexapp.android': 'Plex', 'com.google.android.youtube.tvmusic': 'YouTube Music',
    'com.android.tv.settings': 'TV Settings', 'com.android.vending': 'Play Store',
    'com.tcl.tv': 'Live TV', 'com.tcl.t_solo': 'Bluetooth Audio',
    'com.tcl.dashboard': 'TCL Dashboard', 'com.tcl.exhibit': 'TCL Gallery',
    'com.tcl.suspension': 'TCL Menu', 'com.tcl.partnercustomizer': 'TCL Shortcuts',
    'com.esaba.downloader': 'Downloader', 'com.expressvpn.vpn': 'ExpressVPN',
}


def parse_media(text, foreground=''):
    target = re.search(r'Media button session is (' + PACKAGE + r')/', text)
    sessions = []
    for block in re.split(r'(?m)^\s+package=', text)[1:]:
        package = block.splitlines()[0].strip()
        if not re.fullmatch(PACKAGE, package) or not re.search(r'(?m)^\s*active=true\s*$', block):
            continue
        state = re.search(r'state=PlaybackState\s*\{state=(?:[A-Z_]+\()?([0-9]+)', block)
        if not state or int(state[1]) not in (2, 3, 6, 8):
            continue
        labels = {2: 'Paused', 3: 'Playing', 6: 'Buffering', 8: 'Connecting'}
        metadata = re.search(r'(?m)^\s*metadata:.*?description=(.*)$', block)
        title, subtitle = '', ''
        if metadata:
            parts = metadata[1].strip().rsplit(', ', 2)
            title = parts[0].strip()
            subtitle = parts[1].strip() if len(parts) > 1 else ''
            if title.lower() == 'null': title = ''
            if subtitle.lower() == 'null': subtitle = ''
        value = {'package': package, 'title': title[:300], 'subtitle': subtitle[:200],
                 'state': labels[int(state[1])], 'playing': int(state[1]) == 3}
        score = (package == (target[1] if target else ''), package == foreground, int(state[1]) == 3)
        sessions.append((score, value))
    return max(sessions, key=lambda item: item[0])[1] if sessions else None


def parse_apps(text):
    packages = set()
    for line in text.splitlines():
        component = line.strip()
        if re.fullmatch(PACKAGE + r'/[A-Za-z0-9_.$]+', component):
            packages.add(component.split('/')[0])
    return [{'package': package, 'name': NAMES.get(package, package)}
            for package in sorted(packages, key=lambda item: NAMES.get(item, item).lower())]


def launcher_apps(tv):
    return parse_apps(tv.shell('cmd', 'package', 'query-activities', '--brief',
                              '-a', 'android.intent.action.MAIN', '-c', 'android.intent.category.LEANBACK_LAUNCHER'))


def launch_app(tv, package):
    if not re.fullmatch(PACKAGE, package):
        raise ValueError('Invalid app package.')
    resolved = tv.shell('cmd', 'package', 'resolve-activity', '--brief', '-a',
                        'android.intent.action.MAIN', '-c', 'android.intent.category.LEANBACK_LAUNCHER', package)
    components = [line.strip() for line in resolved.splitlines()
                  if re.fullmatch(re.escape(package) + r'/[A-Za-z0-9_.$]+', line.strip())]
    if len(components) != 1:
        raise RuntimeError('No launchable TV activity found for this app.')
    tv.key('wake')
    output = tv.shell('am', 'start', '-n', shlex.quote(components[0]))
    if re.search(r'(?im)^(?:Error(?: type|:)|Exception|.*SecurityException)', output):
        raise RuntimeError('No launchable TV activity could be opened. ' + output[:300])
