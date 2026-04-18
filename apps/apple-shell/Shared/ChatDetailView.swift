import SwiftUI

struct ChatDetailView: View {
    let store: ChatStore

    var body: some View {
        @Bindable var store = store

        VStack(spacing: 0) {
            header(store: store)
            Divider().overlay(FieldAssistantTheme.hairline)
            content
            Divider().overlay(FieldAssistantTheme.hairline)
            composer(store: store)
        }
        .background(FieldAssistantTheme.appBackground)
    }

    private func header(store: Bindable<ChatStore>) -> some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack(alignment: .top) {
                VStack(alignment: .leading, spacing: 8) {
                    HStack(spacing: 8) {
                        Text(store.statusLabel)
                            .font(.caption.weight(.semibold))
                            .padding(.horizontal, 10)
                            .padding(.vertical, 6)
                            .background(
                                Capsule()
                                    .fill(store.isStreaming ? FieldAssistantTheme.accentMuted : FieldAssistantTheme.elevatedSurface)
                            )

                        Text("Offline-ready")
                            .font(.caption.weight(.semibold))
                            .foregroundStyle(FieldAssistantTheme.subtleText)
                            .padding(.horizontal, 10)
                            .padding(.vertical, 6)
                            .overlay(
                                Capsule()
                                    .stroke(FieldAssistantTheme.hairline, lineWidth: 1)
                            )

                        Text("Unified agent")
                            .font(.caption.weight(.semibold))
                            .foregroundStyle(FieldAssistantTheme.subtleText)
                            .padding(.horizontal, 10)
                            .padding(.vertical, 6)
                            .overlay(
                                Capsule()
                                    .stroke(FieldAssistantTheme.hairline, lineWidth: 1)
                            )
                    }

                    Text(store.selectedConversationTitle)
                        .font(.system(size: 30, weight: .bold, design: .rounded))
                        .lineLimit(2)
                }

                Spacer()
            }
        }
        .padding(24)
    }

    private var content: some View {
        ScrollViewReader { proxy in
            ScrollView {
                if store.messages.isEmpty {
                    VStack(spacing: 14) {
                        Text("TODAY’S PULSE")
                            .font(.caption2.weight(.semibold))
                            .foregroundStyle(FieldAssistantTheme.subtleText)
                            .tracking(1.6)
                        Text("Grounded local chat, approvals, and tool execution in one place.")
                            .font(.system(size: 44, weight: .bold, design: .rounded))
                            .multilineTextAlignment(.center)
                            .frame(maxWidth: 420)
                        Text("Ask for a retrieval-backed summary, a field checklist, or a tool action.")
                            .font(.body)
                            .foregroundStyle(FieldAssistantTheme.subtleText)
                    }
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 100)
                } else {
                    LazyVStack(spacing: 18) {
                        ForEach(store.messages) { message in
                            MessageBubbleView(message: message, store: store)
                                .id(message.id)
                        }
                    }
                    .padding(24)
                }
            }
            .onChange(of: store.messages.count) { _, _ in
                guard let lastID = store.messages.last?.id else {
                    return
                }
                withAnimation(.easeOut(duration: 0.2)) {
                    proxy.scrollTo(lastID, anchor: .bottom)
                }
            }
        }
    }

    private func composer(store: Bindable<ChatStore>) -> some View {
        HStack(alignment: .bottom, spacing: 12) {
            Button {
            } label: {
                Image(systemName: "plus")
                    .font(.title3.weight(.semibold))
                    .frame(width: 46, height: 46)
                    .background(FieldAssistantTheme.elevatedSurface)
                    .clipShape(Circle())
            }
            .buttonStyle(.plain)
            .disabled(true)

            TextField("Ask the local assistant", text: $store.draft, axis: .vertical)
                .textFieldStyle(.plain)
                .padding(.horizontal, 18)
                .padding(.vertical, 14)
                .background(FieldAssistantTheme.elevatedSurface)
                .clipShape(RoundedRectangle(cornerRadius: 22, style: .continuous))
                .lineLimit(1...6)

            Button {
                store.presentVoicePlaceholder()
            } label: {
                Image(systemName: "waveform.circle.fill")
                    .font(.title3)
                    .frame(width: 46, height: 46)
                    .background(FieldAssistantTheme.elevatedSurface)
                    .clipShape(Circle())
            }
            .buttonStyle(.plain)

            Button {
                Task {
                    await store.sendDraft()
                }
            } label: {
                Text("Send")
                    .fontWeight(.bold)
                    .foregroundStyle(.black)
                    .padding(.horizontal, 18)
                    .frame(height: 46)
                    .background(FieldAssistantTheme.accent)
                    .clipShape(Capsule())
            }
            .buttonStyle(.plain)
            .disabled(!store.canSend)
        }
        .padding(.horizontal, 24)
        .padding(.vertical, 18)
        .background(FieldAssistantTheme.appBackground)
    }
}
