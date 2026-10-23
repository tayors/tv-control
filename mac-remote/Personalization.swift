import AppKit
import SwiftUI
import Carbon

struct TVApp: Codable, Identifiable, Equatable {
    let package: String
    let name: String
    var id: String { package }
    static let defaults = [TVApp(package: "com.google.android.youtube.tv", name: "YouTube"),
        TVApp(package: "com.stremio.one", name: "Stremio"), TVApp(package: "com.netflix.ninja", name: "Netflix"),
        TVApp(package: "com.amazon.amazonvideo.livingroom", name: "Prime Video"),
        TVApp(package: "com.disney.disneyplus", name: "Disney+"), TVApp(package: "com.apple.atve.androidtv.appletv", name: "Apple TV")]
    static func validPackage(_ value: String) -> Bool {
        value.range(of: "^[A-Za-z][A-Za-z0-9_]*(\\.[A-Za-z0-9_]+)+$", options: .regularExpression) != nil
    }
    static func slots(_ values: [String]?) -> [String] {
        guard let values = values, values.count == 6 else { return defaults.map(\.package) }
        var seen = Set<String>()
        return values.map { value in
            guard validPackage(value), seen.insert(value).inserted else { return "" }
            return value
        }
    }
}

struct NowPlaying: Decodable {
    let package, title, subtitle, state: String
    let playing: Bool
}

enum QuickAccessMode: String, CaseIterable, Identifiable {
    case controlOptionSpace, controlOptionR, commandOptionR, off
    var id: String { rawValue }
    var title: String {
        switch self { case .controlOptionSpace: return "⌃ ⌥ Space"; case .controlOptionR: return "⌃ ⌥ R"
        case .commandOptionR: return "⌘ ⌥ R"; case .off: return "Off" }
    }
    var key: UInt32 { self == .controlOptionSpace ? 49 : 15 }
    var modifiers: UInt32 { UInt32(optionKey | (self == .commandOptionR ? cmdKey : controlKey)) }
}

final class GlobalQuickAccess {
    var onToggle: (() -> Void)?
    private var hotKey: EventHotKeyRef?
    private var handler: EventHandlerRef?
    private(set) var mode = QuickAccessMode.off
    func register(_ selection: QuickAccessMode) -> OSStatus {
        if selection == mode { return noErr }
        if selection == .off {
            if let hotKey = hotKey { UnregisterEventHotKey(hotKey) }
            hotKey = nil; mode = .off; return noErr
        }
        if handler == nil {
            var event = EventTypeSpec(eventClass: OSType(kEventClassKeyboard), eventKind: UInt32(kEventHotKeyPressed))
            let status = InstallEventHandler(GetApplicationEventTarget(), { _, event, context in
                guard let context = context, let event = event else { return OSStatus(eventNotHandledErr) }
                var identifier = EventHotKeyID()
                let status = GetEventParameter(event, EventParamName(kEventParamDirectObject), EventParamType(typeEventHotKeyID), nil,
                                              MemoryLayout<EventHotKeyID>.size, nil, &identifier)
                guard status == noErr, identifier.signature == 0x5456524D, identifier.id == 1 else { return OSStatus(eventNotHandledErr) }
                let owner = Unmanaged<GlobalQuickAccess>.fromOpaque(context).takeUnretainedValue()
                guard owner.mode != .off else { return OSStatus(eventNotHandledErr) }
                owner.onToggle?()
                return noErr
            }, 1, &event, Unmanaged.passUnretained(self).toOpaque(), &handler)
            if status != noErr { return status }
        }
        var replacement: EventHotKeyRef?
        let status = RegisterEventHotKey(selection.key, selection.modifiers, EventHotKeyID(signature: 0x5456524D, id: 1), GetApplicationEventTarget(), UInt32(kEventHotKeyExclusive), &replacement)
        if status == noErr {
            if let hotKey = hotKey { UnregisterEventHotKey(hotKey) }
            hotKey = replacement; mode = selection
        }
        return status
    }
    deinit {
        if let hotKey = hotKey { UnregisterEventHotKey(hotKey) }
        if let handler = handler { RemoveEventHandler(handler) }
    }
}

extension RemoteState {
    func appName(_ package: String) -> String {
        (installedApps + TVApp.defaults).first(where: { $0.package == package })?.name ?? package
    }
    func setDraftSlot(_ index: Int, to package: String) {
        guard draftShortcuts.indices.contains(index) else { return }
        let previous = draftShortcuts[index]
        if !package.isEmpty, let other = draftShortcuts.firstIndex(of: package), other != index { draftShortcuts[other] = previous }
        draftShortcuts[index] = package
    }
}

extension AppDelegate {
    func personalize() {
        model.draftShortcuts = model.shortcutPackages; model.draftQuickAccess = model.quickAccess
        model.personalizationError = ""; selectPanel("personalize"); loadApps()
    }
    func loadApps() {
        guard !model.appsLoading else { return }
        model.appsLoading = true; model.appsError = ""
        let device = endpoint, address = mac, subnet = broadcast
        catalogQueue.async { [weak self] in
            let result = Self.run("apps", device: device, mac: address, broadcast: subnet, process: Process())
            DispatchQueue.main.async {
                guard let self = self else { return }
                self.model.appsLoading = false
                guard self.endpoint == device else { return }
                struct Catalog: Decodable { let apps: [TVApp] }
                if result.0, let data = result.1.data(using: .utf8), let catalog = try? JSONDecoder().decode(Catalog.self, from: data) {
                    self.model.installedApps = catalog.apps.filter { TVApp.validPackage($0.package) }
                    self.model.appsUpdatedAt = Date()
                    if let data = try? JSONEncoder().encode(self.model.installedApps) { self.defaults.set(data, forKey: "appCatalog") }
                    self.defaults.set(self.model.appsUpdatedAt, forKey: "appsUpdatedAt")
                } else { self.model.appsError = "Couldn’t read TV apps. Reconnect, then refresh this list. Your saved keys are kept." }
            }
        }
    }
    func savePersonalization() {
        let slots = TVApp.slots(model.draftShortcuts)
        guard slots == model.draftShortcuts else { model.personalizationError = "Choose six slots with no repeated apps."; return }
        let status = quickAccess.register(model.draftQuickAccess)
        guard status == noErr else {
            model.personalizationError = "That shortcut is unavailable (\(status)). Choose another combination. Your settings were kept."
            return
        }
        defaults.set(slots, forKey: "appShortcuts")
        defaults.set(model.draftQuickAccess.rawValue, forKey: "quickAccess")
        model.shortcutPackages = slots; model.quickAccess = model.draftQuickAccess; model.quickAccessError = ""
        setFeedback("Personal settings saved.", kind: .success); selectPanel("remote")
    }
}

struct PersonalizationContent: View {
    @ObservedObject var state: RemoteState
    let palette: RemotePalette
    var body: some View {
        VStack(spacing: 0) {
            PanelHeader(title: "Personalize", palette: palette, reading: state.appsLoading, updatedAt: state.appsUpdatedAt,
                        back: { state.action?("panel-remote") }, refresh: { state.action?("refresh-apps") }).padding(.bottom, 16)
            ScrollView {
                VStack(alignment: .leading, spacing: 8) {
                    HStack {
                        Text("Quick access").font(.system(size: 14, weight: .semibold))
                        Spacer()
                        Picker("Open remote", selection: $state.draftQuickAccess) {
                            ForEach(QuickAccessMode.allCases) { Text($0.title).tag($0) }
                        }.labelsHidden().font(.system(size: 12)).fixedSize()
                    }
                    Text("Open or close from any app while TV Remote is running.")
                        .font(.system(size: 11)).foregroundStyle(palette.secondary)
                    if !state.quickAccessError.isEmpty { Text(state.quickAccessError).font(.system(size: 11)).foregroundStyle(palette.failure) }
                    Divider().overlay(palette.line).padding(.vertical, 4)
                    HStack {
                        Text("App keys").font(.system(size: 14, weight: .semibold))
                        Spacer()
                        Button("Reset") { state.draftShortcuts = TVApp.defaults.map(\.package) }.buttonStyle(.plain).font(.system(size: 11))
                    }
                    Text("Six keys, read left to right. Choosing an existing app swaps its position.")
                        .font(.system(size: 11)).foregroundStyle(palette.secondary)
                    ForEach(0..<6, id: \.self) { index in
                        HStack(spacing: 6) {
                            Text("\(index + 1)").font(.system(size: 11)).foregroundStyle(palette.secondary).frame(width: 12)
                            Picker("Key \(index + 1)", selection: Binding(get: { state.draftShortcuts[index] }, set: { state.setDraftSlot(index, to: $0) })) {
                                Text("Empty").tag("")
                                let current = state.draftShortcuts[index]
                                if !current.isEmpty && !state.installedApps.contains(where: { $0.package == current }) {
                                    Text(state.appName(current) + " · saved").tag(current)
                                }
                                ForEach(state.installedApps) { Text($0.name).tag($0.package) }
                            }.labelsHidden().font(.system(size: 12)).frame(maxWidth: .infinity)
                            Button { state.draftShortcuts.swapAt(index, index - 1) } label: { Image(systemName: "chevron.up").frame(width: 24, height: 26) }
                                .disabled(index == 0).help("Move key up").accessibilityLabel("Move key \(index + 1) up")
                            Button { state.draftShortcuts.swapAt(index, index + 1) } label: { Image(systemName: "chevron.down").frame(width: 24, height: 26) }
                                .disabled(index == 5).help("Move key down").accessibilityLabel("Move key \(index + 1) down")
                        }.buttonStyle(RemoteButtonStyle(palette: palette, filled: false, radius: 4))
                    }
                    if !state.appsError.isEmpty { Text(state.appsError).font(.system(size: 11)).foregroundStyle(palette.failure) }
                    if state.installedApps.isEmpty && state.appsError.isEmpty {
                        Text(state.appsLoading ? "Reading installed TV apps…" : "Refresh to read installed TV apps.").font(.system(size: 11)).foregroundStyle(palette.secondary)
                    }
                }.frame(maxWidth: .infinity, alignment: .leading).padding(.bottom, 10)
            }
            VStack(spacing: 8) {
                if !state.personalizationError.isEmpty { Text(state.personalizationError).font(.system(size: 11)).foregroundStyle(palette.failure).fixedSize(horizontal: false, vertical: true) }
                Button { state.action?("save-personalization") } label: { Text("Save personal settings").font(.system(size: 12, weight: .medium)).frame(maxWidth: .infinity).frame(height: 34) }
                    .buttonStyle(RemoteButtonStyle(palette: palette, prominent: true, radius: 6))
                Button("Cancel edits") { state.action?("panel-remote") }.buttonStyle(.plain).font(.system(size: 11)).foregroundStyle(palette.secondary)
            }.padding(.top, 12)
        }
    }
}
