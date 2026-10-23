// Offline fixture renderer. Compiled with -D REMOTE_PREVIEW, never bundled in the app.
import AppKit
import SwiftUI
import Carbon

@main
struct NativePreview {
    @MainActor static func main() throws {
        let app = NSApplication.shared
        app.setActivationPolicy(.prohibited)
        let output = URL(fileURLWithPath: CommandLine.arguments.dropFirst().first ?? "design/native-previews")
        try FileManager.default.createDirectory(at: output, withIntermediateDirectories: true)
        verifyModelGuards()
        var count = 0
        for skin in [RemoteSkin.porcelain, .graphite] {
            for scenario in ["remote", "media", "media-paused", "media-long", "personalize", "personalize-error", "picture", "first-use", "paused", "offline", "recovery", "failure", "hold", "service", "connection"] {
                let state = try fixture(scenario, skin: skin)
                try render(state, height: 548, to: output.appendingPathComponent("\(scenario)-\(skin.rawValue).png"))
                count += 1
            }
            try render(fixture("picture", skin: skin), height: 400, to: output.appendingPathComponent("compact-picture-\(skin.rawValue).png"))
            count += 1
        }
        print("Rendered \(count) native fixture views. No transport or controller actions were run.")
    }

    @MainActor static func fixture(_ scenario: String, skin: RemoteSkin) throws -> RemoteState {
        let model = RemoteState()
        model.skin = skin; model.connected = true; model.power = "Awake"; model.currentApp = "YouTube"
        model.title = "Connected · TV on"; model.subtitle = "YouTube · tv.local:5555"
        model.feedback = "Volume down sent"; model.feedbackKind = .success
        model.statusUpdatedAt = Date(); model.automationUpdatedAt = Date()
        model.draftDevice = "tv.local:5555"; model.draftMAC = "AA:BB:CC:DD:EE:FF"; model.draftBroadcast = "192.0.2.255"
        model.action = { _ in /* Fixture: deliberately no TV transport. */ }
        model.currentPackage = "com.google.android.youtube.tv"
        model.installedApps = TVApp.defaults + [TVApp(package: "com.crunchyroll.crunchyroid", name: "Crunchyroll")]
        model.draftShortcuts = model.shortcutPackages; model.appsUpdatedAt = Date()
        if scenario.hasPrefix("media") {
            model.nowPlaying = NowPlaying(package: "com.google.android.youtube.tv",
                title: scenario == "media-long" ? "A much longer video title, with enough detail to test wrapping and truncation" : "A story worth watching",
                subtitle: "Video creator", state: scenario == "media-paused" ? "Paused" : "Playing", playing: scenario != "media-paused")
        }
        if scenario == "personalize-error" { model.personalizationError = "That shortcut is unavailable. Choose another combination. Your settings were kept." }
        model.panel = scenario == "remote" || scenario.hasPrefix("media") ? "remote" : (scenario.hasPrefix("personalize") ? "personalize" : (scenario == "connection" ? "connection" : "automations"))
        let now = Date().timeIntervalSince1970
        let point: [String: Any] = ["context": [3, 1], "lux": 11.0, "brightness": 41, "time": now - 60]
        var comfort: [String: Any] = ["points": [point, point, point], "pending": ["brightness": 41, "time": now - 20], "revision": "fixture-1"]
        var state: [String: Any] = ["enabled": true, "comfort": comfort, "feedback_undo": ["revision": "fixture-1", "before": 43, "after": 41], "feedback_in_flight": false]
        var json: [String: Any] = [
            "config": ["strategy": "learned"], "state": state,
            "sample": ["awake": true, "lux": 11.0, "sensor_age_seconds": 1, "picture_mode": 3, "backlight": 41, "adaptive_brightness": 1],
            "agent_loaded": true, "last_change": ["time": now - 20, "message": "Picture dimmed a little."],
            "last_check": ["time": now - 30, "reason": "pending_feedback"]
        ]
        switch scenario {
        case "first-use":
            comfort = ["points": [], "revision": "fixture-1"]; state["comfort"] = comfort; state.removeValue(forKey: "feedback_undo")
            json.removeValue(forKey: "last_change")
        case "paused": state["enabled"] = false
        case "offline":
            json["sample"] = NSNull(); json["sample_error"] = "The TV is unavailable."
            model.connected = false; model.title = "Can’t connect to TV"; model.subtitle = "Check Connection and try Refresh."
        case "recovery": state["enabled"] = false; state["feedback_in_flight"] = true
        case "failure": model.automationFailure = true; model.automationFeedback = "Fixture: the picture write could not be verified."
        case "hold": state["hold_until"] = now + 3600
        case "service": json["agent_loaded"] = false
        default: break
        }
        json["state"] = state
        let decoder = JSONDecoder(); decoder.keyDecodingStrategy = .convertFromSnakeCase
        model.automation = try decoder.decode(AutomationSnapshot.self, from: JSONSerialization.data(withJSONObject: json))
        return model
    }

    @MainActor static func render(_ model: RemoteState, height: CGFloat, to url: URL) throws {
        let size = NSSize(width: RemoteLayout.width(for: model.panel), height: height)
        let content = RemoteContent(state: model, height: height).environment(\.colorScheme, model.skin.colorScheme ?? .light).environment(\.controlActiveState, .key)
        let host = NSHostingView(rootView: content)
        let window = NSWindow(contentRect: NSRect(origin: .zero, size: size), styleMask: [.borderless], backing: .buffered, defer: false)
        window.isReleasedWhenClosed = false; window.appearance = model.skin.appearance
        let root = RemoteView(frame: NSRect(origin: .zero, size: size))
        root.addSubview(host); host.frame = root.bounds; window.contentView = root; window.makeFirstResponder(root)
        host.layoutSubtreeIfNeeded(); window.displayIfNeeded()
        RunLoop.current.run(until: Date().addingTimeInterval(0.06))
        host.layoutSubtreeIfNeeded()
        guard let bitmap = host.bitmapImageRepForCachingDisplay(in: host.bounds) else { fatalError("Cannot render \(url.lastPathComponent)") }
        host.cacheDisplay(in: host.bounds, to: bitmap)
        guard let data = bitmap.representation(using: .png, properties: [:]) else { fatalError("Cannot encode render") }
        try data.write(to: url)
        window.close()
    }

    @MainActor static func verifyModelGuards() {
        precondition(RemoteDirection.swipe(CGSize(width: 80, height: 4)) == .right)
        precondition(RemoteDirection.swipe(CGSize(width: -80, height: 4)) == .left)
        precondition(RemoteDirection.swipe(CGSize(width: 4, height: -80)) == .up)
        precondition(RemoteDirection.swipe(CGSize(width: 4, height: 80)) == .down)
        precondition(RemoteDirection.swipe(CGSize(width: 10, height: 4)) == nil)
        let valid = ConnectionPreferences(device: "tv.local:5555", mac: "AA:BB:CC:DD:EE:FF", broadcast: "192.0.2.255")
        precondition(valid.validationError == nil)
        for address in ["tv.local", "tv.local:0", "tv.local:65536", "bad host:5555"] {
            precondition(ConnectionPreferences(device: address, mac: valid.mac, broadcast: valid.broadcast).validationError != nil)
        }
        precondition(ConnectionPreferences(device: valid.device, mac: "invalid", broadcast: valid.broadcast).validationError != nil)
        precondition(ConnectionPreferences(device: valid.device, mac: valid.mac, broadcast: "192.0.2.999").validationError != nil)
        let paused = try! fixture("paused", skin: .porcelain).automation!
        precondition(paused.canUndo && paused.feedbackUnavailable == nil)
        let offline = try! fixture("offline", skin: .porcelain).automation!
        precondition(offline.canUndo && offline.sample == nil && offline.feedbackUnavailable != nil)
        let recovery = try! fixture("recovery", skin: .graphite).automation!
        precondition(recovery.needsRecovery && recovery.canUndo && recovery.feedbackUnavailable != nil)
        let slots = TVApp.defaults.map(\.package)
        precondition(TVApp.slots(nil) == slots)
        precondition(TVApp.slots(["malformed"]) == slots)
        precondition(TVApp.slots(Array(repeating: slots[0], count: 6)) == [slots[0], "", "", "", "", ""])
        let editor = RemoteState(); editor.draftShortcuts = slots
        editor.setDraftSlot(0, to: slots[1])
        precondition(editor.draftShortcuts[0] == slots[1] && editor.draftShortcuts[1] == slots[0])
        precondition(editor.shortcutPackages == slots) // Draft swaps never mutate saved keys.
        editor.setDraftSlot(0, to: ""); precondition(editor.draftShortcuts[0].isEmpty)
        precondition(!TVApp.validPackage("com.example.app; reboot"))
        verifyQuickAccess()
        print("Verified swipe thresholds, connection validation, and paused/offline/recovery guards.")
    }

    @MainActor static func verifyQuickAccess() {
        let shortcut = GlobalQuickAccess()
        var delivered = 0; shortcut.onToggle = { delivered += 1 }
        precondition(shortcut.register(.controlOptionR) == noErr, "Fixture shortcut is unavailable.")
        let competitor = GlobalQuickAccess()
        precondition(competitor.register(.controlOptionR) != noErr, "Shortcut collisions must be reported.")
        precondition(competitor.mode == .off)
        var event: EventRef?
        precondition(CreateEvent(nil, OSType(kEventClassKeyboard), UInt32(kEventHotKeyPressed), 0, 0, &event) == noErr)
        var identifier = EventHotKeyID(signature: 0x5456524D, id: 1)
        precondition(SetEventParameter(event, EventParamName(kEventParamDirectObject), EventParamType(typeEventHotKeyID), MemoryLayout<EventHotKeyID>.size, &identifier) == noErr)
        precondition(SendEventToEventTarget(event, GetApplicationEventTarget()) == noErr)
        if let event = event { ReleaseEvent(event) }
        precondition(delivered == 1)
        precondition(shortcut.register(.off) == noErr)
        precondition(competitor.register(.controlOptionR) == noErr)
        precondition(competitor.register(.off) == noErr)
        print("Verified shortcut editing, native global-key registration, callback delivery, conflict detection and release.")
    }
}
