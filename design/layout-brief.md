# Personal TV remote — Picture comfort iteration

Surface mode: Operate. Native macOS menu-bar application.

## Retained direction

The user retained both Porcelain and Graphite skins from the 2030 remote study. Keep the main remote appearance from `layout-proposal-v4.html`. The user rejected the old Picture comfort presentation as tacky and asked to work on that secondary view next.

## Implemented layout

`layout-proposal-v5.html` records the approved Picture comfort review. The native app implements this layout in both retained skins. The 328 × 548-point panel has one clear state, one shared feedback surface, one automatic-adjustments row, collapsed learning details and a persistent result/Undo footer. It removes the duplicate introductory labels, stacked full-width buttons, and repeated explanations.

- Too dark, Comfortable and Too bright remain immediate feedback commands, not a selected radio group or absolute brightness setting. Comfortable confirms; the other commands make a small adjustment.
- Automatic adjustments have their own switch. Pause preserves current picture and feedback; switching on opens the existing review before any resume. Manual hold and stopped-service states expose explicit Resume. Recovery blocks feedback and resume.
- The footer keeps the latest result and Undo feedback together. Undo uses the existing guarded behavior; when TV readings are unavailable it disables with a reconnect/Refresh explanation. Read-only Refresh has its own header status so it never replaces an action receipt.
- General learning explanations and TV diagnostics remain under Learning details. Availability, failure and recovery reasons stay in the primary view. Example states include first use, an adjustment awaiting feedback, reuse, pause, manual hold, stopped service, unavailable TV, failure and recovery.

## Scope and verification

Implemented and installed in `~/Applications/TV Remote.app` as version 1.4, build 5. The skin preference is saved separately from TV settings. The controller and transport modules, automation snapshot models, and automation request handler are unchanged; the public starter checkout is clean. All 56 existing offline tests pass. The native fixture harness also checks swipe thresholds, connection validation, and paused/offline/recovery guards, and renders 22 views across both skins and a shorter screen height. Native fixtures use example data and send no TV commands. Quit and reopen the installed app to load the new executable. A rollback copy is recorded in `runtime/skin-change-backup.txt`.

Keep the personal project separate from `/Users/tayo/Work/mac-tv-remote`.
