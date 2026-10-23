import AppKit
import SwiftUI

struct RemoteContent: View {
    @ObservedObject var state: RemoteState
    @Environment(\.colorScheme) private var scheme
    var height: CGFloat = RemoteLayout.height
    private var palette: RemotePalette { RemotePalette(skin: state.skin, system: scheme) }
    var body: some View {
        Group {
            switch state.panel {
            case "automations": AutomationContent(state: state, palette: palette)
            case "connection": ConnectionContent(state: state, palette: palette)
            case "personalize": PersonalizationContent(state: state, palette: palette)
            default: RemoteControls(state: state, palette: palette)
            }
        }
        .padding(20)
        .frame(width: RemoteLayout.width(for: state.panel), height: height)
        .foregroundStyle(palette.ink).tint(palette.accent)
        .background(palette.paper, in: RoundedRectangle(cornerRadius: state.panel == "remote" ? 34 : 24))
        .overlay(RoundedRectangle(cornerRadius: state.panel == "remote" ? 34 : 24).strokeBorder(palette.line.opacity(0.75), lineWidth: 1))
        .preferredColorScheme(state.skin.colorScheme)
    }
}

private struct RemoteControls: View {
    @ObservedObject var state: RemoteState
    let palette: RemotePalette
    private func send(_ action: String) { state.action?(action) }
    private func key(_ symbol: String, title: String, command: String, width: CGFloat = 40, filled: Bool = false) -> some View {
        Button { send(command) } label: {
            Image(systemName: symbol).font(.system(size: command == "play-pause" ? 21 : 16, weight: .medium))
                .frame(width: width, height: 36)
        }.buttonStyle(RemoteButtonStyle(palette: palette, filled: filled, radius: 12))
            .disabled(!state.connected && command != "wake").help(title).accessibilityLabel(title)
    }
    private var header: some View {
        HStack(spacing: 4) {
            key("power", title: "Turn on", command: "wake", width: 28)
            Spacer(minLength: 0)
            VStack(spacing: 3) {
                Text("Living room").font(.system(size: 14, weight: .semibold)).tracking(-0.2)
                HStack(spacing: 4) {
                    Circle().fill(state.connected ? palette.accent : palette.failure).frame(width: 3, height: 3)
                    Text(statusLabel).font(.system(size: 10)).lineLimit(1)
                }.foregroundStyle(palette.secondary)
            }.help("\(state.title)\n\(state.subtitle)")
            Spacer(minLength: 0)
            Menu {
                Button("Picture comfort…") { send("panel-automations") }
                Button("Connection…") { send("settings") }
                Button("Personalize…") { send("personalize") }
                Divider()
                Picker("Skin", selection: Binding(get: { state.skin }, set: { send("skin-" + $0.rawValue) })) {
                    ForEach(RemoteSkin.allCases) { Text($0.title).tag($0) }
                }
                Divider()
                Button("Sleep TV") { send("sleep") }.disabled(!state.connected)
                Button("Refresh status") { send("refresh") }.disabled(state.refreshing)
                Button("Reconnect to TV") { send("reconnect") }
                Divider()
                Button("Quit TV Remote") { send("quit") }
            } label: {
                Image(systemName: "gearshape").font(.system(size: 14)).frame(width: 28, height: 30)
            }.menuStyle(.borderlessButton).menuIndicator(.hidden).fixedSize()
                .foregroundStyle(palette.secondary).help("Picture comfort, connection, personal settings, and skin").accessibilityLabel("More controls")
        }.frame(height: 36)
    }
    private var statusLabel: String {
        if !state.connected { return state.refreshing ? "Connecting…" : "Disconnected" }
        if !state.power.isEmpty && state.power != "Awake" { return "TV \(state.power.lowercased())" }
        return state.currentApp.isEmpty ? "Connected" : state.currentApp
    }
    private var transport: some View {
        HStack {
            key("arrow.uturn.backward", title: "Back · Escape", command: "back")
            Spacer()
            key(state.nowPlaying.map { $0.state == "Playing" ? "pause.fill" : ($0.state == "Paused" ? "play.fill" : "playpause.fill") } ?? "playpause.fill", title: "Play / pause · Space", command: "play-pause", width: 66, filled: true)
            Spacer()
            key("house", title: "Home", command: "home")
        }.padding(.horizontal, 10).frame(height: 40)
    }
    private var volume: some View {
        HStack(spacing: 8) {
            key("minus", title: "Volume down", command: "volume-down", width: 32)
            Rectangle().fill(palette.line).frame(height: 1)
            key("speaker.wave.2", title: "Mute / unmute", command: "mute", width: 32)
            Rectangle().fill(palette.line).frame(height: 1)
            key("plus", title: "Volume up", command: "volume-up", width: 32)
        }.frame(height: 34)
    }
    private var appKeys: some View {
        LazyVGrid(columns: [GridItem(.flexible(), spacing: 4), GridItem(.flexible(), spacing: 4)], spacing: 2) {
            ForEach(0..<6, id: \.self) { index in
                let package = state.shortcutPackages[index]
                let name = package.isEmpty ? "Empty" : state.appName(package)
                Button { if package.isEmpty { send("personalize") } else { send("app:" + package) } } label: {
                    Text(name).font(.system(size: 11, weight: state.currentPackage == package && !package.isEmpty ? .semibold : .regular))
                        .lineLimit(1).truncationMode(.tail)
                        .frame(maxWidth: .infinity).frame(height: 23)
                        .background(state.currentPackage == package && !package.isEmpty ? palette.surface : .clear, in: RoundedRectangle(cornerRadius: 6))
                }.buttonStyle(RemoteButtonStyle(palette: palette, filled: false, radius: 6))
                    .disabled(!state.connected && !package.isEmpty).help(package.isEmpty ? "Choose an app for this key" : "Open \(name)")
                    .accessibilityLabel(package.isEmpty ? "Customize empty app key" : "Open \(name)")
            }
        }.padding(6).background(palette.display, in: RoundedRectangle(cornerRadius: 12))
    }
    private var nowPlaying: some View {
        VStack(alignment: .leading, spacing: 3) {
            if state.connected, let media = state.nowPlaying {
                Text("\(media.state) · \(state.appName(media.package))").font(.system(size: 9)).foregroundStyle(palette.secondary).lineLimit(1)
                Text(media.title.isEmpty ? state.appName(media.package) : media.title)
                    .font(.system(size: 12, weight: .medium)).lineLimit(2)
                if !media.subtitle.isEmpty { Text(media.subtitle).font(.system(size: 10)).foregroundStyle(palette.secondary).lineLimit(1) }
            } else {
                Text(state.connected ? (state.currentApp.isEmpty ? "TV connected" : state.currentApp) : "TV unavailable")
                    .font(.system(size: 12, weight: .medium)).lineLimit(1)
                Text(state.connected ? (state.power == "Awake" ? "No playback details available" : "TV in standby") : "Open Connection to reconnect")
                    .font(.system(size: 10)).foregroundStyle(palette.secondary).lineLimit(2)
            }
        }.frame(maxWidth: .infinity, minHeight: 46, alignment: .leading).padding(.horizontal, 10).padding(.vertical, 6)
            .background(palette.display, in: RoundedRectangle(cornerRadius: 10))
            .help(state.nowPlaying.map { "\($0.title)\n\($0.subtitle)\n\($0.state) · Last read \(state.statusUpdatedAt?.formatted(date: .omitted, time: .standard) ?? "now")" } ?? "Some TV apps don’t share playback details.")
    }
    private var receipt: some View {
        HStack(alignment: .center, spacing: 6) {
            if state.busy || state.feedbackKind == .sending { ProgressView().controlSize(.mini).frame(width: 12) }
            else { Image(systemName: state.feedbackKind == .failure ? "exclamationmark.triangle" : "checkmark")
                .font(.system(size: 10)).foregroundStyle(state.feedbackKind == .failure ? palette.failure : palette.accent) }
            Text(state.feedback.isEmpty ? (state.connected ? "Ready" : "Open Connection to reconnect") : state.feedback)
                .font(.system(size: 11)).lineLimit(3).fixedSize(horizontal: false, vertical: true)
                .foregroundStyle(state.feedbackKind == .failure ? palette.failure : palette.secondary)
            if !state.connected {
                Button { send("settings") } label: { Image(systemName: "arrow.up.right").font(.system(size: 11)) }
                    .buttonStyle(.plain).help("Open Connection").accessibilityLabel("Open Connection")
            }
        }.frame(maxWidth: .infinity, minHeight: 30)
            .help(state.feedback.isEmpty ? "Arrow keys navigate · Return selects · Space plays / pauses · Escape sends Back" : state.feedback)
    }
    var body: some View {
        VStack(spacing: 0) {
            header.padding(.bottom, 8)
            ScrollView(.vertical, showsIndicators: true) {
                VStack(spacing: 0) {
                    nowPlaying.padding(.bottom, 6)
                    RemoteTouchSurface(state: state, palette: palette).scaleEffect(0.9).frame(height: 168)
                    transport.padding(.top, 4)
                    volume.padding(.top, 8)
                    appKeys.padding(.top, 10)
                }.frame(maxWidth: .infinity).padding(.bottom, 8)
            }.frame(maxHeight: .infinity)
            receipt.padding(.top, 8)
        }
    }
}

enum RemoteDirection: String, CaseIterable {
    case up, right, down, left
    var title: String { rawValue.capitalized }
    var symbol: String { "chevron." + rawValue }
    var offset: CGSize {
        switch self { case .up: return CGSize(width: 0, height: -64); case .right: return CGSize(width: 64, height: 0)
        case .down: return CGSize(width: 0, height: 64); case .left: return CGSize(width: -64, height: 0) }
    }
    var angle: Double {
        switch self { case .up: return 225; case .right: return -45; case .down: return 45; case .left: return 135 }
    }
    static func swipe(_ translation: CGSize) -> RemoteDirection? {
        guard max(abs(translation.width), abs(translation.height)) >= 26 else { return nil }
        return abs(translation.width) > abs(translation.height)
            ? (translation.width > 0 ? .right : .left) : (translation.height > 0 ? .down : .up)
    }
}

private struct RemoteTouchSurface: View {
    @ObservedObject var state: RemoteState
    let palette: RemotePalette
    @State private var hovered: RemoteDirection?
    @State private var selectHovered = false
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    var body: some View {
        ZStack {
            Circle().strokeBorder(selectHovered ? palette.accent : palette.line, lineWidth: 1).frame(width: 170, height: 170)
            if let direction = hovered {
                Circle().trim(from: 0, to: 0.25).stroke(palette.accent, style: StrokeStyle(lineWidth: 2, lineCap: .round))
                    .rotationEffect(.degrees(direction.angle)).frame(width: 170, height: 170).allowsHitTesting(false)
            }
            ForEach(RemoteDirection.allCases, id: \.self) { direction in
                Button { state.action?(direction.rawValue) } label: {
                    Image(systemName: direction.symbol).font(.system(size: 12, weight: .medium)).frame(width: 44, height: 42)
                }.buttonStyle(RemoteButtonStyle(palette: palette, filled: false, radius: 21))
                    .offset(direction.offset).onHover { hovered = $0 && state.connected ? direction : nil }
                    .help(direction.title).accessibilityLabel(direction.title)
            }
            Button { state.action?("select") } label: {
                Text("OK").font(.system(size: 12, weight: .medium)).frame(width: 64, height: 64)
            }.buttonStyle(RemoteButtonStyle(palette: palette, radius: 32))
                .onHover { selectHovered = $0 && state.connected }.help("Select · Return").accessibilityLabel("Select")
            Text(selectHovered ? "Select" : (hovered?.title ?? "Navigate"))
                .font(.system(size: 9)).foregroundStyle(palette.secondary).offset(y: 38)
                .opacity(hovered != nil || selectHovered ? 1 : 0).allowsHitTesting(false)
        }
        .frame(width: 186, height: 186).contentShape(Circle())
        .disabled(!state.connected).opacity(state.connected ? 1 : 0.45)
        .highPriorityGesture(DragGesture(minimumDistance: 26).onEnded { value in
            guard state.connected, let direction = RemoteDirection.swipe(value.translation) else { return }
            hovered = direction; state.action?(direction.rawValue)
        })
        .onHover { if !$0 { hovered = nil; selectHovered = false } }
        .animation(reduceMotion ? nil : .easeOut(duration: 0.14), value: hovered)
        .accessibilityHint("Swipe to navigate, or use the arrow buttons and Return key")
    }
}

struct ConnectionPreferences {
    var device, mac, broadcast: String
    var validationError: String? {
        let address = device.split(separator: ":", omittingEmptySubsequences: false)
        guard address.count == 2, !address[0].isEmpty, !address[0].contains(where: \.isWhitespace),
              Int(address[1]).map({ (1...65535).contains($0) }) == true else { return "Enter the TV’s ADB host:port, with a port from 1 to 65535." }
        guard mac.range(of: "^([0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}$", options: .regularExpression) != nil else { return "Enter the six-octet Wake MAC address." }
        let parts = broadcast.split(separator: ".", omittingEmptySubsequences: false)
        guard parts.count == 4, parts.allSatisfy({ Int($0).map({ (0...255).contains($0) }) == true }) else { return "Enter an IPv4 broadcast address." }
        return nil
    }
}

private struct ConnectionContent: View {
    @ObservedObject var state: RemoteState
    let palette: RemotePalette
    private func send(_ action: String) { state.action?(action) }
    private func field(_ title: String, text: Binding<String>) -> some View {
        VStack(alignment: .leading, spacing: 5) {
            Text(title).font(.system(size: 12, weight: .medium))
            TextField(title, text: text).textFieldStyle(.plain).font(.system(size: 12))
                .padding(.horizontal, 8).frame(height: 32)
                .background(palette.surface, in: RoundedRectangle(cornerRadius: 6))
                .overlay(RoundedRectangle(cornerRadius: 6).strokeBorder(palette.line, lineWidth: 1))
                .onSubmit { send("save-connection") }
        }
    }
    var body: some View {
        VStack(spacing: 0) {
            PanelHeader(title: "Connection", palette: palette, reading: state.refreshing, updatedAt: state.statusUpdatedAt,
                        back: { send("panel-remote") }, refresh: { send("refresh") }).padding(.bottom, 20)
            ScrollView {
                VStack(alignment: .leading, spacing: 14) {
                    Text(state.title).font(.system(size: 15, weight: .medium))
                    Text(state.subtitle).font(.system(size: 12)).foregroundStyle(palette.secondary).fixedSize(horizontal: false, vertical: true)
                    HStack(spacing: 8) {
                        Button { send("refresh") } label: { Text("Refresh").frame(maxWidth: .infinity).frame(height: 32) }.disabled(state.refreshing)
                        Button { send("reconnect") } label: { Text("Reconnect").frame(maxWidth: .infinity).frame(height: 32) }
                    }.font(.system(size: 12)).buttonStyle(RemoteButtonStyle(palette: palette, radius: 6))
                    Divider().overlay(palette.line)
                    Text("Finds your TV on the same local network and saves its new address. Enter an address below for manual setup.")
                        .font(.system(size: 12)).foregroundStyle(palette.secondary).fixedSize(horizontal: false, vertical: true)
                    field("ADB address", text: $state.draftDevice)
                    field("Wake MAC address", text: $state.draftMAC)
                    field("Broadcast address", text: $state.draftBroadcast)
                    if !state.connectionError.isEmpty {
                        DisclosureGroup("Connection error details") {
                            Text(state.connectionError).font(.system(size: 11)).textSelection(.enabled)
                        }.font(.system(size: 11)).foregroundStyle(palette.secondary)
                    }
                }.frame(maxWidth: .infinity, alignment: .leading).padding(.bottom, 12)
            }.frame(maxHeight: .infinity)
            VStack(spacing: 8) {
                if !state.connectionValidation.isEmpty {
                    Text(state.connectionValidation).font(.system(size: 11)).foregroundStyle(palette.failure)
                        .fixedSize(horizontal: false, vertical: true).frame(maxWidth: .infinity, alignment: .leading)
                }
                Button { send("save-connection") } label: {
                    Text("Save and reconnect").font(.system(size: 12, weight: .medium)).frame(maxWidth: .infinity).frame(height: 34)
                }.buttonStyle(RemoteButtonStyle(palette: palette, prominent: true, radius: 6))
                Button("Cancel edits") { send("cancel-settings") }.buttonStyle(.plain).font(.system(size: 11)).foregroundStyle(palette.secondary)
            }.padding(.top, 12)
        }
    }
}
