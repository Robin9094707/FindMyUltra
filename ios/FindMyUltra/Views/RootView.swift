import SwiftUI

struct RootView: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        ZStack(alignment: .top) {
            if model.isBooting {
                SplashView()
            } else if !model.isConnected {
                ConnectView()
                    .transition(.opacity)
            } else {
                MapScreen()
                    .transition(.opacity)
            }
        }
        .animation(.smooth, value: model.isConnected)
    }
}

struct SplashView: View {
    var body: some View {
        ZStack {
            LinearGradient(colors: [.blue, .indigo, .black], startPoint: .topLeading, endPoint: .bottom).ignoresSafeArea()
            VStack(spacing: 16) {
                Image(systemName: "dot.radiowaves.left.and.right")
                    .font(.system(size: 64, weight: .semibold))
                    .foregroundStyle(.white)
                    .symbolEffect(.variableColor.iterative)
                Text("FindMy Ultra").font(.largeTitle.bold()).foregroundStyle(.white)
            }
        }
    }
}

/// Inhalt des dauerhaften Sheets – Objekte, Mitteilungen, Ich.
struct FindSheet: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        @Bindable var model = model
        NavigationStack(path: $model.sheetPath) {
            root
                .toolbar(.hidden, for: .navigationBar)
                .navigationDestination(for: DeviceRoute.self) { r in
                    if r.recording, let sid = Int(r.id) { RecordingDetailView(recordingID: sid) }
                    else if r.apple { AppleDeviceDetailView(deviceID: r.id) }
                    else { DeviceDetailView(deviceID: r.id) }
                }
        }
        .overlay(alignment: .top) {
            if let t = model.toast {
                ToastView(text: t).padding(.top, 6)
            }
        }
        .animation(.spring(duration: 0.4), value: model.toast)
    }

    private var root: some View {
        VStack(spacing: 0) {
            SectionBar()
                .padding(.horizontal, 16)
                .padding(.top, 14)
                .padding(.bottom, 4)
            Group {
                switch model.section {
                case .items: DeviceListView()
                case .devices: DevicesTabView()
                case .alerts: NotificationsView()
                case .me: SettingsView()
                }
            }
            .frame(maxHeight: .infinity, alignment: .top)
        }
    }
}

struct SectionBar: View {
    @Environment(AppModel.self) private var model
    @Namespace private var ns

    var body: some View {
        GlassEffectContainer(spacing: 6) {
            HStack(spacing: 4) {
                ForEach(SheetSection.allCases) { s in
                    Button {
                        guard model.section != s else { return }
                        Haptics.selection()
                        withAnimation(.spring(duration: 0.35)) { model.section = s }
                        if s == .alerts { model.unreadAlerts = 0 }
                        if model.detent == .peek { model.detent = .medium }
                    } label: {
                        HStack(spacing: 6) {
                            Image(systemName: s.icon)
                            Text(s.short).lineLimit(1).minimumScaleFactor(0.8)
                            if s == .alerts && model.unreadAlerts > 0 {
                                Text("\(model.unreadAlerts)")
                                    .font(.caption2.bold()).padding(.horizontal, 6).padding(.vertical, 1)
                                    .background(.red, in: .capsule).foregroundStyle(.white)
                            }
                        }
                        .font(.footnote.weight(.semibold))
                        .foregroundStyle(model.section == s ? Color.primary : Color.secondary)
                        .padding(.vertical, 9)
                        .frame(maxWidth: .infinity)
                        .background {
                            if model.section == s {
                                Capsule().fill(Color(.tertiarySystemFill))
                                    .matchedGeometryEffect(id: "sel", in: ns)
                            }
                        }
                    }
                    .buttonStyle(.plain)
                }
            }
            .padding(4)
            .glassEffect(.regular, in: .capsule)
        }
    }
}
