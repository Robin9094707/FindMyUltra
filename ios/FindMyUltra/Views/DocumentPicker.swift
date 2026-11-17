import SwiftUI
import UIKit
import UniformTypeIdentifiers

/// Nativer Datei-Picker: lässt JEDE Datei zu (auch .json/.plist mit unbekanntem Typ)
/// und kopiert sie in die App-Sandbox (asCopy) – dadurch keine Rechte-Probleme.
struct DocumentPicker: UIViewControllerRepresentable {
    var onPick: ([URL]) -> Void
    var onCancel: () -> Void

    func makeCoordinator() -> Coordinator { Coordinator(self) }

    func makeUIViewController(context: Context) -> UIDocumentPickerViewController {
        let types: [UTType] = [.item, .content, .data, .json, .propertyList, .text]
        let vc = UIDocumentPickerViewController(forOpeningContentTypes: types, asCopy: true)
        vc.allowsMultipleSelection = true
        vc.shouldShowFileExtensions = true
        vc.delegate = context.coordinator
        return vc
    }

    func updateUIViewController(_ vc: UIDocumentPickerViewController, context: Context) {}

    final class Coordinator: NSObject, UIDocumentPickerDelegate {
        let parent: DocumentPicker
        init(_ p: DocumentPicker) { parent = p }

        func documentPicker(_ controller: UIDocumentPickerViewController, didPickDocumentsAt urls: [URL]) {
            parent.onPick(urls)
        }

        func documentPickerWasCancelled(_ controller: UIDocumentPickerViewController) {
            parent.onCancel()
        }
    }
}
