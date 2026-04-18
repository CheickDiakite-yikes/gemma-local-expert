import SwiftUI

struct ChatShellView: View {
    @State private var store = ChatStore()

    var body: some View {
        @Bindable var store = store

        NavigationSplitView {
            ConversationListView(store: store)
                .navigationSplitViewColumnWidth(min: 270, ideal: 310)
        } detail: {
            ChatDetailView(store: store)
        }
        .preferredColorScheme(.dark)
        .tint(FieldAssistantTheme.accent)
        .background(FieldAssistantTheme.appBackground)
        .task {
            await store.bootstrap()
        }
        .alert("Voice capture is next", isPresented: $store.isShowingVoicePlaceholder) {
            Button("Continue", role: .cancel) { }
        } message: {
            Text("The text chat, streaming, approvals, and session switching are wired. Voice capture and playback are the next layer.")
        }
    }
}
