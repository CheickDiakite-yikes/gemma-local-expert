import SwiftUI

struct ConversationListView: View {
    let store: ChatStore

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                header
                sessionSection
                footer
            }
            .padding(20)
        }
        .background(FieldAssistantTheme.sidebarSurface)
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: 14) {
            VStack(alignment: .leading, spacing: 4) {
                Text("LOCAL-FIRST")
                    .font(.caption2.weight(.semibold))
                    .foregroundStyle(FieldAssistantTheme.subtleText)
                    .tracking(1.6)
                Text("Field Assistant")
                    .font(.system(size: 30, weight: .bold, design: .rounded))
            }

            Button {
                store.startNewConversation()
            } label: {
                Text("New Chat")
                    .fontWeight(.semibold)
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 12)
                    .background(FieldAssistantTheme.accent)
                    .foregroundStyle(.black)
                    .clipShape(RoundedRectangle(cornerRadius: 18, style: .continuous))
            }
            .buttonStyle(.plain)
        }
    }

    private var sessionSection: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("SESSIONS")
                .font(.caption2.weight(.semibold))
                .foregroundStyle(FieldAssistantTheme.subtleText)
                .tracking(1.6)

            if store.conversations.isEmpty {
                Text("No saved sessions yet")
                    .font(.callout)
                    .foregroundStyle(FieldAssistantTheme.subtleText)
            } else {
                VStack(spacing: 10) {
                    ForEach(store.conversations) { conversation in
                        Button {
                            Task {
                                await store.selectConversation(conversation.id)
                            }
                        } label: {
                            VStack(alignment: .leading, spacing: 6) {
                                Text(conversation.title ?? conversation.lastMessagePreview ?? "New conversation")
                                    .font(.headline)
                                    .lineLimit(2)
                                    .multilineTextAlignment(.leading)

                                Text(conversation.lastMessagePreview ?? conversation.mode.title)
                                    .font(.caption)
                                    .foregroundStyle(FieldAssistantTheme.subtleText)
                                    .lineLimit(3)
                                    .multilineTextAlignment(.leading)
                            }
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .padding(14)
                            .background(
                                RoundedRectangle(cornerRadius: 18, style: .continuous)
                                    .fill(
                                        store.selectedConversationID == conversation.id
                                            ? FieldAssistantTheme.panelSurface
                                            : FieldAssistantTheme.elevatedSurface.opacity(0.45)
                                    )
                            )
                            .overlay(
                                RoundedRectangle(cornerRadius: 18, style: .continuous)
                                    .stroke(
                                        store.selectedConversationID == conversation.id
                                            ? FieldAssistantTheme.accent.opacity(0.35)
                                            : FieldAssistantTheme.hairline,
                                        lineWidth: 1
                                    )
                            )
                        }
                        .buttonStyle(.plain)
                    }
                }
            }
        }
    }

    private var footer: some View {
        VStack(alignment: .leading, spacing: 6) {
            Spacer(minLength: 24)
            Text("Engine source of truth: local retrieval, approvals, and MLX runtime.")
                .font(.caption)
                .foregroundStyle(FieldAssistantTheme.subtleText)
            Text("Use this shell for rapid macOS and iOS UX validation before voice.")
                .font(.caption2)
                .foregroundStyle(FieldAssistantTheme.subtleText.opacity(0.9))
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(.top, 30)
    }
}
