import AppKit
import SwiftUI

enum RemoteSkin: String, CaseIterable, Identifiable {
    case system, porcelain, graphite
    var id: String { rawValue }
    var title: String { rawValue.capitalized }
    var colorScheme: ColorScheme? {
        switch self { case .system: return nil; case .porcelain: return .light; case .graphite: return .dark }
    }
    var appearance: NSAppearance? {
        switch self { case .system: return nil; case .porcelain: return NSAppearance(named: .aqua); case .graphite: return NSAppearance(named: .darkAqua) }
    }
}

extension Color {
    init(remoteHex: UInt32) {
        self.init(red: Double((remoteHex >> 16) & 255) / 255,
                  green: Double((remoteHex >> 8) & 255) / 255, blue: Double(remoteHex & 255) / 255)
    }
}

struct RemotePalette {
    let dark: Bool
    let paper, ink, secondary, surface, display, line, accent, selected, failure: Color
    init(skin: RemoteSkin, system: ColorScheme) {
        dark = (skin.colorScheme ?? system) == .dark
        paper = Color(remoteHex: dark ? 0x252C29 : 0xEEECE5)
        ink = Color(remoteHex: dark ? 0xEDF3E9 : 0x363C36)
        secondary = Color(remoteHex: dark ? 0xB5C4B9 : 0x5D685D)
        surface = Color(remoteHex: dark ? 0x2C3530 : 0xF5F4EE)
        display = Color(remoteHex: dark ? 0x2E3932 : 0xE1E5DC)
        line = Color(remoteHex: dark ? 0x47594A : 0xD2D8CD)
        accent = Color(remoteHex: dark ? 0xBED4BC : 0x47624C)
        selected = Color(remoteHex: dark ? 0x394E3E : 0xD6E4D5)
        failure = Color(remoteHex: dark ? 0xF1B4AB : 0x9F2F2D)
    }
}

enum RemoteLayout {
    static var height: CGFloat { min(548, max(240, (NSScreen.main?.visibleFrame.height ?? 900) - 48)) }
    static func width(for panel: String) -> CGFloat { panel == "remote" ? 252 : 328 }
    static func size(for panel: String) -> NSSize { NSSize(width: width(for: panel), height: height) }
}

struct RemoteButtonStyle: ButtonStyle {
    let palette: RemotePalette
    var filled = true
    var prominent = false
    var radius: CGFloat = 8
    @Environment(\.isEnabled) private var enabled
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .foregroundStyle(prominent ? palette.paper : palette.ink)
            .background(background(pressed: configuration.isPressed), in: RoundedRectangle(cornerRadius: radius, style: .circular))
            .overlay(RoundedRectangle(cornerRadius: radius, style: .circular).strokeBorder(palette.line, lineWidth: filled && !prominent ? 1 : 0))
            .opacity(enabled ? 1 : 0.4)
            .scaleEffect(configuration.isPressed ? 0.97 : 1)
            .animation(reduceMotion ? nil : .easeOut(duration: 0.12), value: configuration.isPressed)
    }
    private func background(pressed: Bool) -> Color {
        if prominent { return palette.ink.opacity(pressed ? 0.85 : 1) }
        return pressed ? palette.selected : (filled ? palette.surface : .clear)
    }
}

struct PanelHeader: View {
    let title: String
    let palette: RemotePalette
    var reading = false
    var updatedAt: Date?
    let back: () -> Void
    let refresh: () -> Void
    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Button(action: back) { Label("Remote", systemImage: "chevron.left").font(.system(size: 12)) }
                    .buttonStyle(.plain).foregroundStyle(palette.secondary).help("Return to remote · Escape")
                Spacer(minLength: 6)
                if reading { Text("Reading…").font(.system(size: 10)).foregroundStyle(palette.secondary) }
                else if let date = updatedAt {
                    Text("Read \(date.formatted(date: .omitted, time: .shortened))")
                        .font(.system(size: 10)).foregroundStyle(palette.secondary)
                }
                Button(action: refresh) {
                    ZStack {
                        Image(systemName: "arrow.clockwise").opacity(reading ? 0 : 1)
                        if reading { ProgressView().controlSize(.mini) }
                    }.font(.system(size: 13)).frame(width: 26, height: 26)
                }.buttonStyle(.plain).foregroundStyle(palette.secondary).disabled(reading)
                    .help("Refresh reads status; it does not change the TV").accessibilityLabel("Refresh status")
            }.frame(height: 24)
            Text(title).font(.system(size: 22, weight: .semibold)).tracking(-0.4)
        }.frame(maxWidth: .infinity, alignment: .leading)
    }
}
