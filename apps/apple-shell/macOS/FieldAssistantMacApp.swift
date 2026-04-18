import SwiftUI

@main
struct FieldAssistantMacApp: App {
    var body: some Scene {
        WindowGroup {
            ChatShellView()
                .frame(minWidth: 1180, minHeight: 820)
        }
        .windowResizability(.contentSize)
    }
}
