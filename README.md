# Living-room TV control

Uses the existing authorized ADB connection to the TCL TV. Requires Python 3 and
ADB, both already installed on this Mac. Run from any directory:

```sh
python3 /Users/tayo/Work/tv-control/tv.py status
python3 /Users/tayo/Work/tv-control/tv.py watch youtube
python3 /Users/tayo/Work/tv-control/tv.py watch prime
python3 /Users/tayo/Work/tv-control/tv.py pause
python3 /Users/tayo/Work/tv-control/tv.py play
python3 /Users/tayo/Work/tv-control/tv.py volume-down
python3 /Users/tayo/Work/tv-control/tv.py sleep
python3 /Users/tayo/Work/tv-control/tv.py wake
```

`watch` wakes the TV and opens the selected app. Selecting content and starting
playback still follows that app's UI. Available shortcuts: `youtube`, `prime`,
`netflix`, `disney`, `plex`, and `music`. Use `--help` for navigation commands.
`mute` toggles mute; `wake` and `sleep` send explicit power actions.

Override the device with `--device IP:PORT` or `TV_ADB_DEVICE`. Reconnection is
automatic while the TV's ADB service is reachable. A deep sleep or network change
may require the physical remote or a new device address.

`status` reads existing state. Its lux value is the last sensor event reported by
the TV, not a fresh timed sample or a measurement of screen luminance. TCL's native
Adaptive Brightness was verified ON on 2026-10-20. Android's generic brightness
setting does not establish the native control's panel output.

Remote commands install no TV app. Sensor automation adds the Mac background job
described below. Commands can also be used in Mac Shortcuts. The TV must remain reachable.

## Comfort learning

The Automations panel learns picture comfort from **Too bright**, **Too dark**,
and **Comfortable** feedback. There are no brightness values or lux thresholds
to choose in the app.

- Too bright / Too dark makes one verified three-point adjustment (bounded to
  the supported native range). Automatic changes wait while you decide.
- Comfortable remembers the current brightness with the current room light and
  picture-setting context. It does not change brightness itself.
- When similar light returns in the same supported picture setting, the Mac
  gradually reuses a confirmed preference. In unfamiliar light it leaves the
  picture alone; it never falls back to the old preset curve.
- Undo last feedback restores the previous learning and reverses the last nudge
  if the TV still matches it. A newer TV adjustment is preserved and given a
  one-hour manual hold.

Learning is local memory, not scene recognition or a claim of objectively ideal
brightness. Feedback is explicit: ordinary TV adjustments are respected but are
not silently labelled as Comfortable. Preferences are stored in this workspace,
not sent to an AI service. A new confirmation updates the nearest preference
within the matching light range. At most 50 recent preferences are retained.

Technical matching uses the nearest confirmed light level within a factor of
2 of `(lux + 10)`, separated by picture preset and native HDR *setting*. That
setting is not verified signal detection. No brightness interpolation or
extrapolation is used. The old sensor smoothing, bounded automatic steps,
manual holds, SDK fingerprint checks, native readback checks, Movie-only support,
and protection for high-brightness contexts remain in place.

Commands for the same personal controller:

```sh
python3 tv.py picture status
python3 tv.py picture learn
python3 tv.py picture feedback too-bright
python3 tv.py picture feedback too-dark
python3 tv.py picture feedback comfortable
python3 tv.py picture undo-feedback
python3 tv.py picture disable
python3 tv.py picture enable
```

`learn` switches to learned preferences without connecting to the TV, writing
brightness, or changing the enabled state. It preserves the previous configuration
in `runtime/picture-before-learning.json`. Existing numeric anchor fields remain
for legacy CLI compatibility, but are not used in learned mode. The old
`picture levels` command changes only those legacy anchors.

The background LaunchAgent `local.tayo.tv-picture` checks approximately every
10 seconds while this Mac is awake. It does not wake the TV. Pausing keeps the
current brightness. Feedback still works while paused, but does not turn on
automatic reuse. TV Adaptive Brightness stays on; screen light may influence
the sensor. No calibration in screen nits or reliable HDR signal detection is
claimed. Details of the verified native interface are in `native/api-evidence.json`.

Configuration is in `picture-config.json`; learned preferences, a pending trial,
and undo are in `runtime/picture-state.json`. Feedback changes run under the same
lock as background checks. A recovery record is saved before each picture write.
If a write is interrupted or cannot be verified, automatic changes are blocked
until recovery. A failed verified write also pauses the controller.

## Mac menu-bar remote

Open `~/Applications/TV Remote.app` and click the TV icon in the menu bar.
The native popover has directional controls, Home/Back, volume, playback,
power, and YouTube, Stremio, Netflix, Prime Video, Disney+ and Apple TV shortcuts.
While the popover is focused, arrow keys navigate, Return selects, Space toggles
playback, and Escape sends Back. In secondary views, Escape returns to the remote. The gear menu opens Connection, which saves the ADB endpoint and Wake-on-LAN
addresses for this Mac user. Cancel discards unsaved edits. Refresh only reads TV status.

Turn on sends Wake-on-LAN before retrying ADB. Waking depends on the TV keeping
its network interface available in standby; if it stays unavailable, use the
physical remote, then Refresh. The app uses the existing ADB authorization.

Rebuild/install with `mac-remote/build.sh` (requires Xcode command-line tools).
The app bundles its Python bridge and remote module, and uses an installed
Python 3 and ADB. It has no Dock icon and does not automatically start at login.
Transport checks: `PYTHONPATH=.:mac-remote python3 -m unittest discover -s mac-remote`.

The menu-bar remote now refreshes status independently of navigation commands,
shows a progress indicator and last-updated time, and checks status every five
seconds while open. A refresh never wakes the TV. Connection errors show the
ADB failure instead of assuming the TV is off. Controls pause while disconnected.

Use **gear → Connection → Reconnect** to reset the saved TV's ADB connection.
The native remote also discovers this TV automatically if the saved address
stops working, on launch, Refresh, or its regular status check while open.
It uses ADB mDNS connection advertisements and the known TV MAC in the current
LAN's neighbour table. The saved ADB serial is checked before accepting a changed
address; pairing ports and unrelated devices are excluded. A verified new host
and port are saved automatically. Manual setup remains available in Connection.
Discovery never wakes the TV, sends controls, pairs a new device, or searches
outside the current physical IPv4 LAN. A TV that is asleep, no longer authorized,
or neither advertising nor present under its known MAC may still need manual
setup. A VPN default route is left alone.

If ADB reports “No route to host” while the TV port is reachable, Reconnect can
restart an idle ADB service. It leaves the service alone when other devices are
listed. Reconnect also works when no previous transport exists. Routine Refresh
does not restart ADB. ADB commands have five-second timeouts; connection and
discovery share a 22-second budget, within the app's whole-request timeout.
On macOS, allow TV Remote local-network access if the system requests it.

The separate background picture LaunchAgent retains the address from its last
setup; if the TV address changes, resume automatic adjustments from Picture
comfort to reconfigure that job. Picture actions in the native app use its
newly saved address immediately.

Verified on 2026-10-23: repaired the idle ADB daemon without sending TV controls,
recovered the real TV from an invalid endpoint through mDNS, and confirmed the
installed native app saved the corrected endpoint after launch. All 43 bridge/
discovery tests and 34 picture-policy tests passed. Both skins were rendered
with the updated Connection copy. The public starter repository was unchanged.

## Personal Automations panel

The gear menu opens **Picture comfort** in a secondary view. It explains
whether it is waiting for feedback, reusing a learned preference, paused, waiting
for the TV, or needing recovery. Feedback receipts and **Undo last feedback**
persist across app restarts. Progress and failures remain visible with recovery
instructions. **Refresh** reads status and never changes the TV picture.

The app bundles a private adapter and an `automation-location.json` pointer to
this workspace, so it uses the original state and LaunchAgent. It does not create
a second controller in the app bundle. This personal integration is not included
in the public `mac-tv-remote` repository. Sound profiles and sleep schedules are
not implemented.


## Appearance and compact controls

The personal native app uses the reviewed remote layout, with a navigation ring,
Back/Home, playback, volume and all six app shortcuts on the main view. Swiping
the navigation surface sends one directional step; the arrow buttons and keyboard
controls remain available. Short screens scroll the controls while keeping the
latest action receipt visible.

Choose **gear → Skin → System, Porcelain, or Graphite**. The choice is saved for
this Mac user and applies immediately to every view. System follows macOS light
or dark appearance. Skin changes do not alter TV or picture-learning preferences.

Picture comfort separates feedback from automatic adjustments. Its latest result
and guarded **Undo feedback** stay visible below scrolling details. Turning on or
resuming automatic adjustments still requires review. Refresh has a separate
read timestamp and never replaces the last action receipt.

The native UI is in `mac-remote/RemoteUI.swift`, `Appearance.swift`, and
`Automation.swift`; the existing controller and transport stay in their original
modules. All personal integration remains separate from the public starter.

Run `mac-remote/verify-ui.sh` to render offline native fixtures in both skins,
including paused, disconnected, recovery and short-screen states. These fixture
renders send no TV commands. The installed app must be quit and reopened after a
rebuild to load the new executable.


## Now playing and personal controls

The main remote reads the active Android media session for a title, creator and
Playing/Paused/Buffering state. The playback key reflects confirmed Playing or
Paused state. It refreshes about every five seconds while open, and after playback
commands. Some TV apps expose no metadata; those show the foreground app and an
honest unavailable message. Hover over the media display for the full title and
last-read time. Missing metadata never disables otherwise working controls.
Artwork, duration and a seek slider are not exposed by this implementation.

**Control–Option–Space** opens or closes the remote globally while the app is
running, returning directly to the main remote when opening it. No keyboard
monitoring or Accessibility permission is needed. In **gear → Personalize**, choose
Control–Option–R, Command–Option–R, or Off instead. A conflicting registration is
reported without replacing saved settings. The app does not start automatically
at login.

The same Personalize view lets you choose six app keys from the TV's launcher
apps, move them up/down, or leave slots empty. Choosing an app already in another
slot swaps the two keys. Reset restores the original six in the draft; Save
persists it, while Cancel or returning to Remote discards draft changes. Editing
and refreshing never launch apps. App names are cached locally for future launches;
the editor refreshes the list from the TV. Removed apps fail without disconnecting
the remote. Custom launching validates the package and exact resolved launcher
component before sending it to Android's shell.

Implementation: `mac-remote/Personalization.swift` owns personal controls and
native global hotkeys; `media_apps.py` owns media parsing and validated launcher
queries. Preferences stay in this Mac user's app defaults. The controller,
learning state and public starter remain separate.

Verified on 2026-10-23 for version 1.6: 96 Python tests passed, 32 native fixture
views rendered, and native shortcut registration, delivery, conflict and release
checks passed. Live read-only checks confirmed YouTube metadata and 18 launcher
apps. The installed app was reopened and its global shortcut registration checked.
No playback or app-launch commands were sent during verification.
