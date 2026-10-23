# Personal TV remote

<!-- impeccable:product-schema 1 -->

## Platform

macOS — native menu-bar application built with SwiftUI and AppKit. This platform
is outside Impeccable's web/iOS/Android platform enum; do not treat it as iOS.

## Users

The owner of this personal project controls their TV from their Mac.

## Product Purpose

Make navigation, volume, playback, and app launching compact and easy to
understand. Picture learning and connection settings belong in secondary views.
Action feedback and picture-feedback undo must remain clear.

## Capabilities and Constraints

- Preserve the existing remote commands, keyboard controls, power actions, and
  six native-app shortcuts.
- Preserve local picture-comfort learning, pause/resume, recovery, receipts, and
  guarded undo. Reuse the existing controller and its state.
- Preserve connection preferences, read-only Refresh, explicit Reconnect, and
  the existing bounded ADB transport.
- Keep this project separate from `/Users/tayo/Work/mac-tv-remote`, the public
  starter repository. Personal integrations and settings stay here.
- Show a proposed layout before implementing the app redesign.

## Evidence on Hand

- `README.md`: documented workflows, local controller, and operating limits.
- `mac-remote/Remote.swift`: current UI and remote-command handling.
- `mac-remote/Automation.swift`: picture-learning UI, receipts, and recovery.
- Existing Python tests cover transport, picture learning, and safe undo.

## Product Principles

- Look and feel like a real handheld remote: a narrow body, familiar directional ring, tactile keys, volume rocker, and dedicated app buttons. This user direction supersedes the rejected flat utility-panel proposals.

- Retain both Porcelain and Graphite skins.
- Put everyday control actions first.
- Use progressive disclosure for setup and picture learning.
- Distinguish action progress, confirmed results, and failures.
- Preserve working behavior while changing presentation.

## Implementation

The user retained both Porcelain and Graphite skins from the 2030 remote study. Keep both appearances and the handheld identity. The revised Picture comfort view was approved, and the user requested implementation as a changeable skin. The native app now has a saved System/Porcelain/Graphite preference separate from TV and learning settings. Main controls, Picture comfort, and Connection use the selected skin.
