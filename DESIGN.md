# TV Remote design

## Selected direction

The user retained both skins from the 2030 remote study: Porcelain and Graphite. Keep the narrow physical-remote silhouette and continuous navigation surface. `design/layout-proposal-v4.html` records the retained remote appearance. The revised Picture comfort layout from `design/layout-proposal-v5.html` was approved for implementation. The native app now implements the remote and secondary views with a saved Skin selection: System, Porcelain, or Graphite.

Use native macOS system typography and SF Symbols. Preserve system light/dark appearance as the baseline. All proposed controls must remain usable with a pointer and keyboard; gestures supplement explicit controls.

## Appearance tokens

| Role | Porcelain | Graphite |
| --- | --- | --- |
| Body | `#EEECE5` | `#252C29` |
| Primary text | `#363C36` | `#EDF3E9` |
| Secondary text | `#5D685D` | `#B5C4B9` |
| Raised surface | `#F5F4EE` | `#2C3530` |
| Recessed surface | `#E1E5DC` | `#2E3932` |
| Contour | `#D2D8CD` | `#47594A` |
| Semantic accent | `#47624C` | `#BED4BC` |

Use quiet contours and restrained press feedback. Avoid gradients, neon, decorative glass, heavy shadows, and repeated card containers. Rounded shapes belong to the remote body and tactile controls. The main frame target is 252 × 548 points; secondary views expand to a readable 328-point width. Verify dimensions in native rendering.

## Hierarchy

Navigation, Back, Home, playback, volume and six app shortcuts lead the remote. The foreground app may be highlighted using existing status data. Do not invent media metadata, absolute volume values, voice controls, or TV capabilities.

Picture comfort and Connection are secondary destinations with a clear Remote return. General explanation and technical readings use progressive disclosure. UI copy describes confirmed controller behavior, including unfamiliar light being left alone.

## Picture comfort requirements

Keep feedback and automatic adjustments distinct. Too dark and Too bright make one small adjustment; Comfortable confirms the current picture for similar light. Do not replace this learning workflow with an absolute brightness slider or a fake comfort score.

Pausing preserves the current picture and keeps valid feedback available. Starting or resuming automatic adjustments retains the existing review and availability checks. Manual hold, stopped service, unavailable TV, unsupported conditions, action failure and recovery need clear states derived from the existing snapshot.

Action progress, confirmed results and failures have a stable home. Status refresh updates independently and must not overwrite action receipts. Undo explicitly targets the last feedback, uses the existing revision guard, and never promises an unconditional TV rollback. Persisted controller receipts remain the source of truth. Keep unavailable/recovery reasons visible rather than hiding them in details.

## Project boundary

This is the personal integration in `/Users/tayo/Work/tv-control`. Do not copy personal controller integration, endpoints, local state or diagnostics into the public starter at `/Users/tayo/Work/mac-tv-remote`.


## Now playing and personalization

The v6 proposal adds a quiet, compact media display above the navigation ring in
the existing 252 × 548-point body. The ring scales to 90% to preserve space for
all six app keys. Show actual title, creator and playback state when reported;
otherwise identify the foreground app and missing playback details. Long titles
truncate after two lines, with the full text and read time available on hover.
Do not add invented artwork, time positions or duration.

Gear → Personalize is a secondary, scrollable view with a pinned Save/Cancel
footer. Quick access uses a native global shortcut, with alternative combinations
and Off. Six app slots select installed launchable TV apps, reorder, swap and
clear without launching. Both skins and all existing action receipts remain.
