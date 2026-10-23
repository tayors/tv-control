import AppKit
import SwiftUI

enum ActionFeedbackKind { case idle, sending, success, failure, notice }

final class RemoteState: ObservableObject {
    @Published var title = "Connecting to TV"
    @Published var subtitle = "Checking the saved connection…"
    @Published var feedback = ""
    @Published var connected = false
    @Published var refreshing = false
    @Published var busy = false
    @Published var endpoint = ""
    @Published var currentApp = ""
    @Published var currentPackage = ""
    @Published var nowPlaying: NowPlaying?
    @Published var shortcutPackages = TVApp.defaults.map(\.package)
    @Published var draftShortcuts = TVApp.defaults.map(\.package)
    @Published var installedApps: [TVApp] = []
    @Published var appsLoading = false
    @Published var appsError = ""
    @Published var appsUpdatedAt: Date?
    @Published var quickAccess = QuickAccessMode.controlOptionSpace
    @Published var draftQuickAccess = QuickAccessMode.controlOptionSpace
    @Published var quickAccessError = ""
    @Published var personalizationError = ""
    @Published var panel = "remote"
    @Published var skin = RemoteSkin.system
    @Published var feedbackKind = ActionFeedbackKind.idle
    @Published var power = ""
    @Published var statusUpdatedAt: Date?
    @Published var connectionError = ""
    @Published var draftDevice = ""
    @Published var draftMAC = ""
    @Published var draftBroadcast = ""
    @Published var connectionValidation = ""
    @Published var automation: AutomationSnapshot?
    @Published var automationBusy = false
    @Published var automationFeedback = ""
    @Published var automationFailure = false
    @Published var automationOperation = ""
    @Published var automationUpdatedAt: Date?
    var action: ((String) -> Void)?
}

final class RemoteView: NSView {
    var command: ((String) -> Void)?
    override var acceptsFirstResponder: Bool { true }
    override func keyDown(with event: NSEvent) {
        if !event.modifierFlags.intersection([.command, .control, .option]).isEmpty { super.keyDown(with: event); return }
        let keys: [UInt16: String] = [123:"left",124:"right",125:"down",126:"up",36:"select",49:"play-pause",53:"back"]
        if let action = keys[event.keyCode] { command?(action) } else { super.keyDown(with: event) }
    }
}

final class AppDelegate: NSObject, NSApplicationDelegate {
    let item = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
    let popover = NSPopover()
    let model = RemoteState()
    let root = RemoteView()
    let defaults = UserDefaults.standard
    let commands = DispatchQueue(label: "local.tayo.tvremote.commands")
    let statusQueue = DispatchQueue(label: "local.tayo.tvremote.status")
    let automationQueue = DispatchQueue(label: "local.tayo.tvremote.automation")
    let catalogQueue = DispatchQueue(label: "local.tayo.tvremote.catalog")
    let quickAccess = GlobalQuickAccess()
    var hostingView: NSHostingView<RemoteContent>?
    var latestAction = UUID()
    var statusProcess: Process?
    var statusID = UUID()
    var pending = 0
    var lastRefresh = Date.distantPast
    var refreshTimer: Timer?
    var endpoint: String { defaults.string(forKey: "device") ?? "192.168.1.44:5555" }
    var mac: String { defaults.string(forKey: "mac") ?? "3c:c5:dd:1f:c6:a6" }
    var broadcast: String { defaults.string(forKey: "broadcast") ?? "192.168.1.255" }

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.accessory)
        item.button?.image = NSImage(systemSymbolName: "tv", accessibilityDescription: "TV Remote")
        item.button?.target = self; item.button?.action = #selector(toggle)
        item.button?.toolTip = "Living room TV"
        model.skin = RemoteSkin(rawValue: defaults.string(forKey: "skin") ?? "system") ?? .system
        model.shortcutPackages = TVApp.slots(defaults.stringArray(forKey: "appShortcuts"))
        if let data = defaults.data(forKey: "appCatalog"), let apps = try? JSONDecoder().decode([TVApp].self, from: data) {
            model.installedApps = apps.filter { TVApp.validPackage($0.package) }
            model.appsUpdatedAt = defaults.object(forKey: "appsUpdatedAt") as? Date
        }
        model.quickAccess = QuickAccessMode(rawValue: defaults.string(forKey: "quickAccess") ?? "controlOptionSpace") ?? .controlOptionSpace
        quickAccess.onToggle = { [weak self] in
            guard let self = self else { return }
            if self.popover.isShown { self.popover.performClose(nil) }
            else { self.send("panel-remote"); self.show() }
        }
        if quickAccess.register(model.quickAccess) != 0 { model.quickAccessError = "Quick access is unavailable. Choose another shortcut." }
        popover.appearance = model.skin.appearance
        model.action = { [weak self] in self?.send($0) }
        root.command = { [weak self] action in
            guard let self = self else { return }
            if self.model.panel == "remote" { self.send(action) }
            else if action == "back" { self.send("panel-remote") }
        }
        let host = NSHostingView(rootView: RemoteContent(state: model))
        hostingView = host
        let size = RemoteLayout.size(for: model.panel)
        root.frame = NSRect(origin: .zero, size: size)
        host.frame = root.bounds; host.autoresizingMask = [.width, .height]
        root.wantsLayer = true; root.layer?.backgroundColor = NSColor.clear.cgColor
        root.addSubview(host)
        let controller = NSViewController(); controller.view = root
        popover.contentViewController = controller; popover.behavior = .transient; popover.contentSize = size
        refresh()
        refreshTimer = Timer.scheduledTimer(withTimeInterval: 5, repeats: true) { [weak self] _ in
            guard let self = self, self.popover.isShown, !self.model.refreshing, self.pending == 0 else { return }
            self.refresh()
            if self.model.panel == "automations" { self.requestAutomation() }
        }
        DispatchQueue.main.async { self.show() }
    }
    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool { show(); return false }
    func show() {
        guard !popover.isShown, let button = item.button else { return }
        popover.show(relativeTo: button.bounds, of: button, preferredEdge: .minY)
        NSApp.activate(ignoringOtherApps: true)
        root.window?.makeFirstResponder(root)
        if Date().timeIntervalSince(lastRefresh) > 5 && !model.refreshing { refresh() }
    }
    @objc func toggle() { if popover.isShown { popover.performClose(nil) } else { show() } }
    func send(_ action: String) {
        if action.hasPrefix("skin-"), let skin = RemoteSkin(rawValue: String(action.dropFirst(5))) {
            defaults.set(skin.rawValue, forKey: "skin")
            model.skin = skin; popover.appearance = skin.appearance
            return
        }
        switch action {
        case "panel-remote":
            if model.panel == "connection" { resetConnectionDraft() }
            selectPanel("remote")
        case "panel-automations": selectPanel("automations"); requestAutomation()
        case "personalize": personalize()
        case "save-personalization": savePersonalization()
        case "refresh-apps": loadApps()
        case "save-connection": saveConnection()
        case "cancel-settings": resetConnectionDraft(); selectPanel("remote")
        case "quit": NSApp.terminate(nil)
        case "settings": settings()
        case "refresh":
            refresh()
            if model.panel == "automations" { requestAutomation() }
        case "automation-status": requestAutomation()
        case "automation-pause": requestAutomation("pause")
        case "automation-resume": requestAutomation("resume")
        case "automation-too-bright": requestAutomation("too-bright")
        case "automation-too-dark": requestAutomation("too-dark")
        case "automation-comfortable": requestAutomation("comfortable")
        case "automation-undo-feedback": requestAutomation("undo-feedback")
        case "reconnect": refresh(reconnect: true)
        default:
            guard model.connected || action == "wake" else { setFeedback("Connect to the TV before sending controls.", kind: .failure); return }
            execute(action)
        }
    }
    func refresh(reconnect: Bool = false) {
        if model.refreshing && !reconnect { return }
        // Refresh has its own queue and cancels a previous status request.
        if let process = statusProcess, process.isRunning { process.terminate() }
        let id = UUID(); statusID = id
        let process = Process(); statusProcess = process
        let device = endpoint, address = mac, subnet = broadcast
        let serial = defaults.string(forKey: "tvSerial") ?? ""
        model.endpoint = device; model.refreshing = true
        let receiptID = reconnect ? UUID() : nil
        if let receiptID = receiptID { latestAction = receiptID; setFeedback("Reconnecting to TV…", kind: .sending) }
        model.title = reconnect ? "Reconnecting…" : (model.connected ? "Connected" : "Connecting to TV")
        model.subtitle = "Checking \(device)…"
        statusQueue.async { [weak self] in
            let result = Self.run(reconnect ? "reconnect" : "status", device: device, mac: address, broadcast: subnet, process: process, extra: ["--discover", "--serial", serial])
            DispatchQueue.main.async {
                guard let self = self, self.statusID == id, self.endpoint == device else { return }
                self.model.refreshing = false; self.statusProcess = nil
                self.lastRefresh = Date()
                if result.0, let data = result.1.data(using: .utf8), let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
                    let resolved = json["endpoint"] as? String ?? device
                    let preferences = ConnectionPreferences(device: resolved, mac: address, broadcast: subnet)
                    guard preferences.validationError == nil else { self.connectionFailed("The TV returned an invalid connection address."); return }
                    if let serial = json["serial"] as? String, !serial.isEmpty { self.defaults.set(serial, forKey: "tvSerial") }
                    if resolved != device {
                        self.defaults.set(resolved, forKey: "device")
                        self.model.endpoint = resolved; self.model.automation = nil
                        self.model.installedApps = []; self.model.appsUpdatedAt = nil
                        if self.model.draftDevice == device { self.model.draftDevice = resolved }
                    }
                    self.model.connected = true
                    self.model.connectionError = ""
                    self.model.statusUpdatedAt = Date()
                    let power = json["power"] as? String ?? "unknown"
                    self.model.power = power
                    let app = json["foreground_app"] as? String ?? ""
                    self.model.currentPackage = app
                    self.model.nowPlaying = nil
                    if let media = json["now_playing"] as? [String: Any], let data = try? JSONSerialization.data(withJSONObject: media) {
                        self.model.nowPlaying = try? JSONDecoder().decode(NowPlaying.self, from: data)
                    }
                    let names = ["com.stremio.one":"Stremio", "com.google.android.youtube.tv":"YouTube", "com.netflix.ninja":"Netflix", "com.amazon.amazonvideo.livingroom":"Prime Video", "com.google.android.apps.tv.launcherx":"Google TV home", "com.disney.disneyplus":"Disney+", "com.apple.atve.androidtv.appletv":"Apple TV"]
                    self.model.currentApp = names[app] ?? app
                    if self.model.currentApp == app { self.model.currentApp = self.model.appName(app) }
                    self.model.title = power == "Awake" ? "Connected · TV on" : "Connected · \(power.lowercased())"
                    self.model.subtitle = "\(self.model.currentApp.isEmpty ? "Ready to control" : self.model.currentApp) · \(resolved)"
                    if let receiptID = receiptID, self.latestAction == receiptID {
                        self.setFeedback(resolved == device ? "Reconnected to TV." : "TV found at \(resolved). Address updated.", kind: .success)
                    }
                    self.item.button?.image = NSImage(systemSymbolName: "tv", accessibilityDescription: "TV connected")
                } else {
                    self.connectionFailed(result.1)
                    if let receiptID = receiptID, self.latestAction == receiptID { self.setFeedback("Couldn’t reconnect. Check Connection.", kind: .failure) }
                }
            }
        }
    }
    func connectionFailed(_ error: String) {
        model.connected = false; model.title = "Can’t connect to TV"; model.nowPlaying = nil
        let text = error.trimmingCharacters(in: .whitespacesAndNewlines)
        model.connectionError = text
        if text.localizedCaseInsensitiveContains("unauthorized") || text.localizedCaseInsensitiveContains("authorization") {
            model.subtitle = "Accept the ADB authorization prompt on the TV."
        } else if text.contains("No route to host") {
            model.subtitle = "Network access failed. Open Connection and try Reconnect."
        } else if text.localizedCaseInsensitiveContains("refused") {
            model.subtitle = "TV refused ADB. Check its debugging setting."
        } else { model.subtitle = String(text.prefix(130)) }
        NSLog("TV Remote: %@", text)
    }
    func execute(_ action: String) {
        guard pending < 3 else { setFeedback("Waiting for the TV. Try again in a moment.", kind: .notice); return }
        pending += 1; model.busy = true
        let id = UUID(); latestAction = id
        let device = endpoint, address = mac, subnet = broadcast
        let labels = ["select": "Select", "play-pause": "Play / pause", "wake": "Turn on", "sleep": "Sleep",
                      "youtube": "YouTube", "stremio": "Stremio", "netflix": "Netflix", "prime": "Prime Video", "disney": "Disney+", "apple": "Apple TV"]
        let label = action.hasPrefix("app:") ? model.appName(String(action.dropFirst(4))) : (labels[action] ?? action.replacingOccurrences(of: "-", with: " ").capitalized)
        setFeedback(action == "wake" ? "Sending wake signal…" : "Sending \(label.lowercased())…", kind: .sending)
        commands.async { [weak self] in
            let result = Self.run(action, device: device, mac: address, broadcast: subnet, process: Process())
            DispatchQueue.main.async {
                guard let self = self else { return }
                self.pending -= 1; self.model.busy = self.pending > 0
                guard self.endpoint == device else { return }
                if result.0 {
                    if self.latestAction == id { self.setFeedback("\(label) sent", kind: .success) }
                    if !self.model.connected || action.hasPrefix("app:") || ["play-pause", "wake", "sleep", "home", "youtube", "stremio", "prime", "netflix", "disney", "apple"].contains(action) { self.refresh() }
                } else if result.1.contains("No launchable TV activity") {
                    if self.latestAction == id { self.setFeedback("This app is not available on the TV.", kind: .failure) }
                } else {
                    self.connectionFailed(result.1)
                    if self.latestAction == id { self.setFeedback("Command failed. Open Connection.", kind: .failure) }
                    self.refresh()
                }
            }
        }
        root.window?.makeFirstResponder(root)
    }
    func setFeedback(_ text: String, kind: ActionFeedbackKind) {
        model.feedback = text; model.feedbackKind = kind
    }
    func selectPanel(_ panel: String) {
        model.panel = panel
        let size = RemoteLayout.size(for: panel)
        root.setFrameSize(size); hostingView?.frame = root.bounds; popover.contentSize = size
        if panel == "remote" { root.window?.makeFirstResponder(root) }
    }
    static func run(_ action: String, device: String, mac: String, broadcast: String, process: Process, extra: [String] = []) -> (Bool, String) {
        guard let resources = Bundle.main.resourceURL else { return (false, "App resources are missing. Reinstall TV Remote.") }
        let pythonCandidates = ["/opt/homebrew/bin/python3", "/usr/local/bin/python3", "/usr/bin/python3"]
        guard let python = pythonCandidates.first(where: { FileManager.default.isExecutableFile(atPath: $0) }) else { return (false, "Python 3 was not found.") }
        let pipe = Pipe()
        process.executableURL = URL(fileURLWithPath: python)
        process.arguments = ["-B", resources.appendingPathComponent("remote_bridge.py").path, "--device", device, "--mac", mac, "--broadcast", broadcast, action == "play-pause" ? "toggle-playback" : action]
        process.arguments?.append(contentsOf: extra)
        if action.hasPrefix("app:") {
            let package = String(action.dropFirst(4))
            guard TVApp.validPackage(package) else { return (false, "Invalid app shortcut.") }
            process.arguments = ["-B", resources.appendingPathComponent("remote_bridge.py").path, "--device", device, "launch-app", "--package", package]
        }
        process.standardOutput = pipe; process.standardError = pipe
        let timeout = DispatchWorkItem { if process.isRunning { process.terminate() } }
        do {
            try process.run()
            DispatchQueue.global().asyncAfter(deadline: .now() + (action == "wake" ? 38 : (action.hasPrefix("automation-") ? 30 : 25)), execute: timeout)
            let output = pipe.fileHandleForReading.readDataToEndOfFile()
            process.waitUntilExit(); timeout.cancel()
            let text = String(data: output, encoding: .utf8) ?? ""
            return (process.terminationStatus == 0, text.isEmpty && process.terminationStatus != 0 ? "Connection was interrupted or timed out. Try Refresh." : text)
        } catch { timeout.cancel(); return (false, error.localizedDescription) }
    }
    func resetConnectionDraft() {
        model.draftDevice = endpoint; model.draftMAC = mac; model.draftBroadcast = broadcast
        model.connectionValidation = ""
    }
    func settings() {
        resetConnectionDraft(); selectPanel("connection")
    }
    func saveConnection() {
        let preferences = ConnectionPreferences(device: model.draftDevice.trimmingCharacters(in: .whitespacesAndNewlines),
                                               mac: model.draftMAC.trimmingCharacters(in: .whitespacesAndNewlines),
                                               broadcast: model.draftBroadcast.trimmingCharacters(in: .whitespacesAndNewlines))
        if let error = preferences.validationError { model.connectionValidation = error; return }
        if preferences.device != endpoint || preferences.mac.caseInsensitiveCompare(mac) != .orderedSame { defaults.removeObject(forKey: "tvSerial") }
        for (key, value) in [("device", preferences.device), ("mac", preferences.mac), ("broadcast", preferences.broadcast)] { defaults.set(value, forKey: key) }
        resetConnectionDraft(); model.automation = nil
        model.installedApps = []; model.appsUpdatedAt = nil
        refresh(reconnect: true)
    }
}
#if !REMOTE_PREVIEW
@main
struct TVRemoteApp {
    static func main() {
        let app = NSApplication.shared
        let delegate = AppDelegate()
        app.delegate = delegate
        withExtendedLifetime(delegate) { app.run() }
    }
}

#endif
