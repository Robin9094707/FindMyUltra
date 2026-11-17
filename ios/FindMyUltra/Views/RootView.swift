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
                MainTabs()
                    .transition(.opacity)
            }
            if let t = model.toast {
                ToastView(text: t)
                    .padding(.top, 54)
                    .zIndex(10)
            }
        }
        .animation(.smooth, value: model.isConnected)
        .animation(.spring(duration: 0.4), value: model.toast)
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

struct MainTabs: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        @Bindable var model = model
        TabView(selection: $model.tab) {
            Tab("Karte", systemImage: "map.fill", value: AppTab.map) {
                NavigationStack(path: $model.mapPath) {
                    MapScreen()
                        .navigationDestination(for: DeviceRoute.self) { DeviceDetailView(deviceID: $0.id) }
                }
            }
            Tab("Objekte", systemImage: "circle.grid.2x2.fill", value: AppTab.items) {
                NavigationStack(path: $model.itemsPath) {
                    DeviceListView()
                        .navigationDestination(for: DeviceRoute.self) { DeviceDetailView(deviceID: $0.id) }
                }
            }
            Tab("Mitteilungen", systemImage: "bell.badge.fill", value: AppTab.alerts) {
                NavigationStack(path: $model.alertsPath) {
                    NotificationsView()
                        .navigationDestination(for: DeviceRoute.self) { DeviceDetailView(deviceID: $0.id) }
                }
            }
            .badge(model.unreadAlerts)
            Tab("Einstellungen", systemImage: "gearshape.fill", value: AppTab.settings) {
                NavigationStack {
                    SettingsView()
                }
            }
        }
        .tabBarMinimizeBehavior(.onScrollDown)
        .onChange(of: model.tab) { _, t in
            if t == .alerts { model.unreadAlerts = 0 }
        }
    }
}
