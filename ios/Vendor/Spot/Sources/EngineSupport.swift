// Small non-UI support layer for the extracted Spot protocol engine. GPL-3.0-only.
import Foundation
import Combine
import UIKit

extension Notification.Name { static let googleEngineError = Notification.Name("RJGoogleEngineError") }
func showAlert(title: String, message: String) {
    DispatchQueue.main.async { NotificationCenter.default.post(name: .googleEngineError, object: nil, userInfo: ["message": message]) }
}
func runAfter(seconds: Double, _ action: @escaping () -> Void) { DispatchQueue.main.asyncAfter(deadline: .now() + seconds, execute: action) }
func isSimulator() -> Bool {
    #if targetEnvironment(simulator)
    true
    #else
    false
    #endif
}
func errorVibration() { DispatchQueue.main.async { UINotificationFeedbackGenerator().notificationOccurred(.error) } }
func doubleVibration() { DispatchQueue.main.async { UINotificationFeedbackGenerator().notificationOccurred(.success) } }
extension String { func localized() -> String { NSLocalizedString(self, comment: "") } }
func deviceNotCurrentlyReachable(device: BluetoothTempData, currentDate: Date, timeout: Int = Int(Constants.scanInterval * 2)) -> Bool {
    currentDate.timeIntervalSince(device.last_update_publisher) > Double(timeout)
}



/// FindMy Ultra: Prüft die im Info.plist angemeldeten Hintergrundmodi, bevor die Engine
/// Hintergrund-APIs nutzt, die ohne Anmeldung zum sofortigen Beenden der App führen.
enum SpotBackgroundModes {
    static let modes: Set<String> = Set((Bundle.main.object(forInfoDictionaryKey: "UIBackgroundModes") as? [String]) ?? [])
    static func has(_ mode: String) -> Bool { modes.contains(mode) }
}
