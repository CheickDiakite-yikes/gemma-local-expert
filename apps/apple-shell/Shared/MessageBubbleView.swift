import SwiftUI

struct MessageBubbleView: View {
    let message: ChatMessage
    let store: ChatStore

    var body: some View {
        HStack {
            if message.role == .user {
                Spacer(minLength: 80)
            }

            VStack(alignment: .leading, spacing: 12) {
                Text(message.role.title.uppercased())
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(FieldAssistantTheme.subtleText)
                    .tracking(1.4)

                Text(message.content)
                    .font(.body)
                    .foregroundStyle(textColor)
                    .textSelection(.enabled)

                if let proposedToolName = message.proposedToolName {
                    Text("Prepared \(proposedToolName)")
                        .font(.caption.weight(.semibold))
                        .padding(.horizontal, 10)
                        .padding(.vertical, 6)
                        .background(FieldAssistantTheme.elevatedSurface)
                        .clipShape(Capsule())
                }

                if !message.citations.isEmpty {
                    LazyVGrid(columns: [GridItem(.adaptive(minimum: 120), spacing: 8)], alignment: .leading, spacing: 8) {
                        ForEach(message.citations) { citation in
                            Text(citation.label)
                                .font(.caption.weight(.medium))
                                .padding(.horizontal, 10)
                                .padding(.vertical, 7)
                                .background(FieldAssistantTheme.elevatedSurface)
                                .clipShape(Capsule())
                        }
                    }
                }

                if let approval = message.approval {
                    approvalCard(approval)
                }
            }
            .padding(18)
            .frame(maxWidth: 700, alignment: .leading)
            .background(bubbleColor)
            .clipShape(RoundedRectangle(cornerRadius: 24, style: .continuous))
            .overlay(
                RoundedRectangle(cornerRadius: 24, style: .continuous)
                    .stroke(message.role == .user ? Color.clear : FieldAssistantTheme.hairline, lineWidth: 1)
            )

            if message.role != .user {
                Spacer(minLength: 80)
            }
        }
    }

    private var bubbleColor: Color {
        switch message.role {
        case .assistant, .system:
            return FieldAssistantTheme.assistantBubble
        case .user:
            return FieldAssistantTheme.userBubble
        }
    }

    private var textColor: Color {
        message.role == .user ? .black : .white
    }

    private func approvalCard(_ approval: ApprovalStateDTO) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            Text(approval.toolName)
                .font(.headline)
            Text(approval.reason)
                .font(.subheadline)
                .foregroundStyle(FieldAssistantTheme.subtleText)
            Text(approval.payload.prettyPrintedString)
                .font(.system(.caption, design: .monospaced))
                .textSelection(.enabled)
                .foregroundStyle(FieldAssistantTheme.subtleText)

            Text("Status: \(approval.status)")
                .font(.caption.weight(.semibold))

            if let result = approval.result {
                Text(result.prettyPrintedString)
                    .font(.system(.caption, design: .monospaced))
                    .textSelection(.enabled)
            }

            if approval.status == "pending" {
                HStack(spacing: 10) {
                    Button {
                        Task {
                            await store.resolveApproval(approval, action: "approve")
                        }
                    } label: {
                        Text("Approve")
                            .fontWeight(.bold)
                            .foregroundStyle(.black)
                            .padding(.horizontal, 14)
                            .padding(.vertical, 9)
                            .background(FieldAssistantTheme.success)
                            .clipShape(Capsule())
                    }
                    .buttonStyle(.plain)
                    .disabled(store.activeApprovalID != nil)

                    Button {
                        Task {
                            await store.resolveApproval(approval, action: "reject")
                        }
                    } label: {
                        Text("Reject")
                            .fontWeight(.semibold)
                            .padding(.horizontal, 14)
                            .padding(.vertical, 9)
                            .background(FieldAssistantTheme.elevatedSurface)
                            .clipShape(Capsule())
                    }
                    .buttonStyle(.plain)
                    .disabled(store.activeApprovalID != nil)
                }
            }
        }
        .padding(14)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(FieldAssistantTheme.panelSurface.opacity(0.82))
        .clipShape(RoundedRectangle(cornerRadius: 18, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 18, style: .continuous)
                .stroke(FieldAssistantTheme.accent.opacity(0.22), lineWidth: 1)
        )
    }
}
