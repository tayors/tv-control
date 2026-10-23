import AppKit
import SwiftUI

struct ComfortConfiguration: Decodable {
    let strategy: String?
}
struct ComfortPoint: Decodable {
    let context: [Int]
    let lux: Double
    let brightness: Int
    let time: Double
}
struct ComfortTrial: Decodable {
    let brightness: Int
    let time: Double
}
struct ComfortMemory: Decodable {
    let points: [ComfortPoint]?
    let pending: ComfortTrial?
    let revision: String?
}
struct FeedbackUndo: Decodable {
    let revision: String
    let before: Int
    let after: Int
}
struct BrightnessControllerState: Decodable {
    let enabled: Bool
    let holdUntil: Double?
    let comfort: ComfortMemory?
    let feedbackUndo: FeedbackUndo?
    let feedbackInFlight: Bool?
}
struct PictureSample: Decodable {
    let awake: Bool
    let lux: Double?
    let sensorAgeSeconds: Double?
    let pictureMode: Int?
    let backlight: Int?
    let adaptiveBrightness: Int?
}
struct AutomationChange: Decodable {
    let time: Double
    let message: String
}
struct AutomationCheck: Decodable {
    let time: Double
    let reason: String?
    let curveTarget: Int?
    let targetSource: String?
}
struct AutomationSnapshot: Decodable {
    let config: ComfortConfiguration
    let state: BrightnessControllerState
    let sample: PictureSample?
    let sampleError: String?
    let agentLoaded: Bool
    let message: String?
    let lastChange: AutomationChange?
    let lastCheck: AutomationCheck?
    var manualHold: Bool { state.enabled && (state.holdUntil ?? 0) > Date().timeIntervalSince1970 }
    var recentCheck: Bool { lastCheck.map { Date().timeIntervalSince1970 - $0.time < 45 && $0.time >= (lastChange?.time ?? 0) } ?? false }
    var learnedCount: Int { state.comfort?.points?.count ?? 0 }
    var trial: Bool { state.comfort?.pending != nil }
    var needsRecovery: Bool { state.feedbackInFlight == true }
    var canUndo: Bool { state.feedbackUndo?.revision != nil && state.feedbackUndo?.revision == state.comfort?.revision }
    var feedbackUnavailable: String? {
        if config.strategy != "learned" { return "Comfort learning is being set up. Refresh shortly." }
        if needsRecovery { return "Undo last feedback to recover the unconfirmed adjustment." }
        guard let sample = sample else { return "Cannot read the TV. Check it is on and on the same network, then Refresh." }
        if !sample.awake { return "Turn on the TV, then Refresh to give feedback." }
        if sample.pictureMode != 3 { return "Switch the TV to Movie picture mode, then Refresh. Other presets are not supported yet." }
        if sample.adaptiveBrightness != 1 { return "Turn on Adaptive Brightness in the TV’s settings so its light sensor is available." }
        if !(5...85).contains(sample.backlight ?? 0) { return "This picture setting is outside the supported adjustment range. Use the TV’s picture controls." }
        if sample.lux == nil || (sample.sensorAgeSeconds ?? .infinity) > 30 { return "Waiting for a fresh light-sensor reading. Refresh before giving feedback." }
        return nil
    }
    var controllerTitle: String {
        if needsRecovery { return "An adjustment needs recovery" }
        if !state.enabled { return "Automatic adjustments are paused" }
        if !agentLoaded { return "The background service has stopped" }
        if feedbackUnavailable != nil { return "Waiting for the TV" }
        if manualHold { return "Your manual change takes priority" }
        if trial { return "How does the picture feel now?" }
        if learnedCount == 0 { return "Ready to learn what you like" }
        if recentCheck && lastCheck?.reason == "unlearned_light" { return "New room light to learn" }
        if !recentCheck || lastCheck?.targetSource != "comfort_feedback" { return "Checking your saved preferences" }
        return "Using a preference you taught me"
    }
    var controllerDetail: String {
        if needsRecovery { return "The last picture change could not be confirmed. Automatic adjustments are blocked. Undo last feedback to recover." }
        if !state.enabled { return "Saved preferences will not be applied automatically. You can still adjust and teach the picture with the buttons below." }
        if !agentLoaded { return "Restart to reuse your preferences in the background. Your current picture is being left alone." }
        if let reason = feedbackUnavailable { return reason }
        if manualHold, let until = state.holdUntil { return "You changed the TV brightness manually. Automatic adjustments are on hold until \(Self.clock(until)). Feedback below can teach that choice." }
        if trial { return "I’m keeping your latest adjustment. Choose Comfortable to remember it, or adjust it again. I won’t make automatic changes while you decide." }
        if learnedCount == 0 { return "Tell me how the picture feels. I’ll remember what you mark Comfortable and reuse it in similar room light. There are no brightness numbers to set." }
        if recentCheck && lastCheck?.reason == "unlearned_light" { return "I haven’t learned a preference for this light yet, so I’m leaving the picture alone. Tell me how it feels below." }
        if recentCheck && lastCheck?.targetSource == "comfort_feedback" {
            return lastCheck?.reason == "deadband" ? "The TV already matches a brightness you marked Comfortable in similar room light. No adjustment is needed." : "I’m gradually returning to a brightness you marked Comfortable in similar room light. You can correct it below."
        }
        return "I only reuse confirmed preferences in similar room light. Your current picture is kept when there is no match."
    }
    static func clock(_ time: Double) -> String {
        DateFormatter.localizedString(from: Date(timeIntervalSince1970: time), dateStyle: .none, timeStyle: .short)
    }
}

struct AutomationContent: View {
    @ObservedObject var state: RemoteState
    let palette: RemotePalette
    @State private var reviewStart = false
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    private func send(_ action: String) { state.action?(action) }
    private func note(_ text: String, size: CGFloat = 12) -> some View {
        Text(text).font(.system(size: size)).foregroundStyle(palette.secondary).fixedSize(horizontal: false, vertical: true)
    }
    private func summary(_ snapshot: AutomationSnapshot) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(summaryTitle(snapshot)).font(.system(size: 18, weight: .medium)).tracking(-0.3)
                .fixedSize(horizontal: false, vertical: true)
            note(summaryDetail(snapshot))
        }.frame(maxWidth: .infinity, alignment: .leading)
    }
    private func summaryTitle(_ snapshot: AutomationSnapshot) -> String {
        if snapshot.needsRecovery || !snapshot.state.enabled || !snapshot.agentLoaded || snapshot.feedbackUnavailable != nil || snapshot.manualHold {
            return snapshot.controllerTitle
        }
        if snapshot.trial { return "Keep this picture?" }
        return snapshot.learnedCount == 0 ? "How’s the picture?" : snapshot.controllerTitle
    }
    private func summaryDetail(_ snapshot: AutomationSnapshot) -> String {
        if snapshot.state.enabled && snapshot.agentLoaded && snapshot.feedbackUnavailable == nil && !snapshot.manualHold && snapshot.trial {
            return "Your last adjustment stays in place while you decide."
        }
        return snapshot.controllerDetail
    }
    private func choice(_ title: String, symbol: String, command: String, confirm: Bool = false) -> some View {
        Button { send(command) } label: {
            VStack(spacing: 10) {
                Image(systemName: symbol).font(.system(size: 21, weight: confirm ? .medium : .regular))
                    .foregroundStyle(confirm ? palette.accent : palette.ink).frame(height: 24)
                Text(title).font(.system(size: 12, weight: .medium)).lineLimit(1)
            }.frame(maxWidth: .infinity).frame(height: 74)
                .background(confirm ? palette.surface : .clear, in: RoundedRectangle(cornerRadius: 8))
        }.buttonStyle(RemoteButtonStyle(palette: palette, filled: false))
    }
    private func feedback(_ snapshot: AutomationSnapshot) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 4) {
                choice("Too dark", symbol: "sun.min", command: "automation-too-dark")
                    .help("Make the picture a little brighter")
                choice("Comfortable", symbol: "checkmark", command: "automation-comfortable", confirm: true)
                    .help("Remember the picture as it is for similar room light")
                choice("Too bright", symbol: "sun.max", command: "automation-too-bright")
                    .help("Make the picture a little dimmer")
            }.padding(6).background(palette.display, in: RoundedRectangle(cornerRadius: 12))
                .disabled(state.automationBusy || snapshot.feedbackUnavailable != nil)
            if let unavailable = snapshot.feedbackUnavailable, !snapshot.needsRecovery, unavailable != summaryDetail(snapshot) {
                note(unavailable, size: 11)
            } else if snapshot.feedbackUnavailable == nil {
                note("Comfortable remembers it for similar light.", size: 11)
            }
        }
    }
    private func automatic(_ snapshot: AutomationSnapshot) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            Rectangle().fill(palette.line).frame(height: 1).padding(.bottom, 7)
            HStack(spacing: 12) {
                VStack(alignment: .leading, spacing: 3) {
                    Text("Automatic adjustments").font(.system(size: 13, weight: .medium))
                    note(automaticDetail(snapshot), size: 11)
                }.frame(maxWidth: .infinity, alignment: .leading)
                Toggle("Automatic adjustments", isOn: Binding(get: { snapshot.state.enabled }, set: { enabled in
                    if enabled { reviewStart = true }
                    else { reviewStart = false; send("automation-pause") }
                })).labelsHidden().toggleStyle(.switch).controlSize(.small)
                    .disabled(state.automationBusy || (!snapshot.state.enabled && snapshot.needsRecovery))
            }
            if snapshot.state.enabled && (!snapshot.agentLoaded || snapshot.manualHold) {
                Button("Resume adjustments…") { reviewStart.toggle() }.buttonStyle(.plain)
                    .font(.system(size: 11)).disabled(state.automationBusy || snapshot.needsRecovery)
            }
            if reviewStart {
                VStack(alignment: .leading, spacing: 9) {
                    note("Reuse confirmed preferences while this Mac is awake. This ends any manual hold; unfamiliar room light is left alone.", size: 11)
                    HStack(spacing: 14) {
                        Button { reviewStart = false; send("automation-resume") } label: {
                            Text("Turn on").font(.system(size: 11, weight: .medium)).padding(.horizontal, 10).frame(height: 30)
                        }.buttonStyle(RemoteButtonStyle(palette: palette))
                            .disabled(state.automationBusy || snapshot.sample?.awake != true || snapshot.needsRecovery)
                        Button("Cancel") { reviewStart = false }.buttonStyle(.plain).font(.system(size: 11)).foregroundStyle(palette.secondary)
                    }
                    if snapshot.sample?.awake != true { note("Turn on the TV and Refresh before starting.", size: 11) }
                }.id("resume-review")
            }
        }
    }
    private func automaticDetail(_ snapshot: AutomationSnapshot) -> String {
        if snapshot.needsRecovery { return "Blocked until recovery" }
        if snapshot.manualHold { return "On hold · manual change" }
        if snapshot.state.enabled && !snapshot.agentLoaded { return "Background service unavailable" }
        return snapshot.state.enabled ? "On · confirmed preferences only" : "Off · current picture stays"
    }
    private func learningDetails(_ snapshot: AutomationSnapshot) -> some View {
        DisclosureGroup {
            VStack(alignment: .leading, spacing: 8) {
                note("Comfortable saves a preference for similar room light. Too dark and Too bright make one small adjustment; they do not confirm a preference.", size: 11)
                note("Preferences stay on this Mac and are learned only from your feedback, never from old brightness presets. Marking Comfortable again updates the preference for similar light.", size: 11)
                note("Pause keeps the current picture and leaves feedback available. A manual TV brightness change takes priority for one hour. This Mac must be awake and connected.", size: 11)
                note("Learning uses room light and the current picture setting. It does not recognize scenes or infer comfort. Movie mode and Adaptive Brightness are required; high-brightness settings are preserved.", size: 11)
                note("Experimental: screen light can affect the sensor, and HDR detection is unverified. No sound or sleep routines run.", size: 11)
                if let sample = snapshot.sample {
                    note("TV brightness: \(sample.backlight.map(String.init) ?? "unavailable") /100. Light sensor: \(sample.lux.map { $0.formatted(.number.precision(.fractionLength(0...1))) + " lux" } ?? "unavailable").", size: 11)
                }
                if let date = state.automationUpdatedAt { note("TV read at \(AutomationSnapshot.clock(date.timeIntervalSince1970)).", size: 11) }
                if let check = snapshot.lastCheck { note("Last background check at \(AutomationSnapshot.clock(check.time)).", size: 11) }
                if let error = snapshot.sampleError { Text(error).font(.system(size: 11)).textSelection(.enabled) }
            }.padding(.top, 8)
        } label: {
            HStack {
                Text("Learning details")
                Spacer(minLength: 4)
                Text(snapshot.learnedCount == 0 ? "Nothing saved yet" : "\(snapshot.learnedCount) remembered").font(.system(size: 10))
            }
        }.font(.system(size: 11)).foregroundStyle(palette.secondary)
    }
    private var failureDetails: some View {
        VStack(alignment: .leading, spacing: 8) {
            note("Refresh to check what took effect. Undo feedback can recover the last adjustment. Pause stops automatic changes.", size: 11)
            DisclosureGroup("Error details") {
                Text(state.automationFeedback).font(.system(size: 11)).textSelection(.enabled)
            }.font(.system(size: 11))
            Button("Dismiss error") { state.automationFailure = false; state.automationFeedback = "" }
                .buttonStyle(.plain).font(.system(size: 11))
        }.foregroundStyle(palette.secondary)
    }
    private var resultMessage: String {
        if !state.automationOperation.isEmpty { return state.automationOperation }
        if state.automationFailure || state.automation?.needsRecovery == true { return "Action could not be confirmed" }
        if let change = state.automation?.lastChange { return change.message }
        if let message = state.automation?.message, !message.isEmpty { return message }
        return state.automation == nil ? "Waiting for picture status" : "No feedback yet"
    }
    private var resultFooter: some View {
        let failed = state.automationFailure || state.automation?.needsRecovery == true
        return VStack(alignment: .leading, spacing: 7) {
            Rectangle().fill(palette.line).frame(height: 1).padding(.bottom, 5)
            HStack(alignment: .top, spacing: 10) {
                HStack(alignment: .top, spacing: 6) {
                    if !state.automationOperation.isEmpty { ProgressView().controlSize(.mini).frame(width: 12, height: 18) }
                    else { Image(systemName: failed ? "exclamationmark.triangle" : "checkmark")
                        .font(.system(size: 10)).foregroundStyle(failed ? palette.failure : palette.accent).frame(width: 12, height: 18) }
                    Text(resultMessage).font(.system(size: 12)).foregroundStyle(failed && state.automationOperation.isEmpty ? palette.failure : palette.ink)
                        .fixedSize(horizontal: false, vertical: true)
                }.frame(maxWidth: .infinity, alignment: .leading)
                    .help(state.automation?.lastChange.map { "Last action at \(AutomationSnapshot.clock($0.time))" } ?? resultMessage)
                if let snapshot = state.automation, snapshot.canUndo {
                    Button { send("automation-undo-feedback") } label: {
                        Label("Undo feedback", systemImage: "arrow.uturn.backward").font(.system(size: 11))
                    }.buttonStyle(.plain).disabled(state.automationBusy || snapshot.sample == nil)
                        .help("Remove the last feedback. Reverse its picture adjustment only if the TV has not changed since.")
                        .accessibilityLabel("Undo last feedback")
                }
            }
            if let snapshot = state.automation, snapshot.canUndo {
                note(snapshot.sample == nil ? "Reconnect to the TV, then Refresh to undo." : "Reverses its picture adjustment only if the TV hasn’t changed since.", size: 11)
            }
        }.padding(.top, 14)
    }
    var body: some View {
        VStack(spacing: 0) {
            PanelHeader(title: "Picture comfort", palette: palette,
                        reading: state.automationBusy && state.automationOperation.isEmpty, updatedAt: state.automationUpdatedAt,
                        back: { send("panel-remote") }, refresh: { send("automation-status") })
            ScrollViewReader { proxy in
                ScrollView {
                    VStack(alignment: .leading, spacing: 0) {
                    if let snapshot = state.automation {
                        summary(snapshot)
                        feedback(snapshot).padding(.top, 18)
                        if state.automationFailure { failureDetails.padding(.top, 16) }
                        automatic(snapshot).padding(.top, 23)
                        learningDetails(snapshot).padding(.top, 18)
                    } else {
                        note(state.automationBusy ? "Reading the TV and your learned preferences…" : "Status is unavailable. Refresh to try again.")
                        if state.automationFailure { failureDetails.padding(.top, 16) }
                    }
                    }.frame(maxWidth: .infinity, alignment: .leading).padding(.top, 26).padding(.bottom, 8)
                }.onChange(of: reviewStart) { reviewing in
                    if reviewing {
                        DispatchQueue.main.async {
                            withAnimation(reduceMotion ? nil : .easeOut(duration: 0.18)) { proxy.scrollTo("resume-review", anchor: .bottom) }
                        }
                    }
                }
            }.frame(maxHeight: .infinity)
            resultFooter
        }
    }
}

extension AppDelegate {
    func requestAutomation(_ action: String = "status") {
        guard !model.automationBusy else { return }
        model.automationBusy = true
        if action != "status" {
            model.automationFailure = false
            model.automationOperation = ["pause": "Pausing automatic adjustments…", "resume": "Starting automatic adjustments…",
                                         "too-bright": "Making the picture a little dimmer…", "too-dark": "Making the picture a little brighter…",
                                         "comfortable": "Remembering this picture…", "undo-feedback": "Undoing your last feedback…"][action] ?? "Updating…"
        }
        let device = endpoint, address = mac, subnet = broadcast
        automationQueue.async { [weak self] in
            let result = Self.run("automation-" + action, device: device, mac: address, broadcast: subnet, process: Process())
            DispatchQueue.main.async {
                guard let self = self else { return }
                self.model.automationBusy = false
                self.model.automationOperation = ""
                guard self.endpoint == device else { self.model.automation = nil; return }
                if result.0, let data = result.1.data(using: .utf8) {
                    do {
                        let decoder = JSONDecoder(); decoder.keyDecodingStrategy = .convertFromSnakeCase
                        self.model.automation = try decoder.decode(AutomationSnapshot.self, from: data)
                        self.model.automationUpdatedAt = Date()
                        if action != "status" { self.model.automationFailure = false; self.requestAutomation() }
                    } catch {
                        self.model.automationFailure = true
                        self.model.automationFeedback = "The controller response could not be read: \(error.localizedDescription)"
                        if action != "status" { self.requestAutomation() }
                    }
                } else {
                    self.model.automationFailure = true
                    self.model.automationFeedback = result.1.trimmingCharacters(in: .whitespacesAndNewlines)
                    if action != "status" { self.requestAutomation() }
                }
            }
        }
    }
}
