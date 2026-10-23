#!/bin/zsh
set -eu
REMOTE_SOURCE_DIR="${0:A:h}"
REMOTE_PROJECT_DIR="${REMOTE_SOURCE_DIR:h}"
REMOTE_RENDER_DIR="${1:-$REMOTE_PROJECT_DIR/design/native-previews}"
mkdir -p "$REMOTE_PROJECT_DIR/runtime" "$REMOTE_RENDER_DIR"
xcrun swiftc -D REMOTE_PREVIEW \
    "$REMOTE_SOURCE_DIR/Remote.swift" "$REMOTE_SOURCE_DIR/RemoteUI.swift" \
    "$REMOTE_SOURCE_DIR/Personalization.swift" "$REMOTE_SOURCE_DIR/Appearance.swift" "$REMOTE_SOURCE_DIR/Automation.swift" \
    "$REMOTE_PROJECT_DIR/design/NativePreview.swift" \
    -target "$(uname -m)-apple-macosx13.0" -o "$REMOTE_PROJECT_DIR/runtime/remote-native-preview" \
    -framework AppKit -framework SwiftUI
"$REMOTE_PROJECT_DIR/runtime/remote-native-preview" "$REMOTE_RENDER_DIR"
