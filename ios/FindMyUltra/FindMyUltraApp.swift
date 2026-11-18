import SwiftUI
import UserNotifications
import SpotIntegration

final class NotificationDelegate: NSObject, UNUserNotificationCenterDelegate {
    var onOpen: (@MainActor (URL) -> Void)?

    func userNotificationCenter(_ center: UNUserNotificationCenter, willPresent notification: UNNotification,
                                withCompletionHandler completionHandler: @escaping (UNNotificationPresentationOptions) -> Void) {
        completionHandler([.banner, .sound, .list])
    }

    func userNotificationCenter(_ center: UNUserNotificationCenter, didReceive response: UNNotificationResponse,
                                withCompletionHandler completionHandler: @escaping () -> Void) {
        if let s = response.notification.request.content.userInfo["url"] as? String, let u = URL(string: s) {
            Task { @MainActor in self.onOpen?(u) }
        }
        completionHandler()
    }
}

@main
struct FindMyUltraApp: App {
    @State private var model = AppModel()
    @Environment(\.scenePhase) private var scenePhase
    private let notificationDelegate = NotificationDelegate()

    init() {
        UNUserNotificationCenter.current().delegate = notificationDelegate
    }

    var body: some Scene {
        WindowGroup {
            RootView()
                .environment(model)
                .task {
                    notificationDelegate.onOpen = { [model] url in model.handle(url: url) }
                    await model.boot()
                }
                .onOpenURL { model.handle(url: $0) }
                .onChange(of: scenePhase) { _, phase in
                    switch phase {
                    case .active:
                        if model.isConnected {
                            model.startLive()
                            model.markOpened()
                            Task { try? await model.loadAll() }
                        }
                        GoogleTrackerStore.shared.sceneChanged(active: true)
                    case .background:
                        model.markBackground()
                        model.stopLive()
                        GoogleTrackerStore.shared.sceneChanged(active: false)
                        Task { await GoogleLink.shared.push() }
                    default: break
                    }
                }
        }
    }
}
