import Foundation
import Observation

@MainActor
@Observable
final class ChatStore {
    var conversations: [ConversationSummaryDTO] = []
    var selectedConversationID: String?
    var mode: AssistantMode = .general
    var draft: String = ""
    var isStreaming = false
    var statusLabel = "Ready"
    var isShowingVoicePlaceholder = false
    var activeApprovalID: String?

    @ObservationIgnored
    private let client: FieldAssistantAPIClient

    @ObservationIgnored
    private var didBootstrap = false

    @ObservationIgnored
    private var messagesByConversation: [String: [ChatMessage]] = [:]

    init(client: FieldAssistantAPIClient = FieldAssistantAPIClient()) {
        self.client = client
    }

    var selectedConversationTitle: String {
        if let selectedConversation = conversations.first(where: { $0.id == selectedConversationID }) {
            return selectedConversation.title ?? selectedConversation.lastMessagePreview ?? "Field Assistant"
        }
        return "New conversation"
    }

    var messages: [ChatMessage] {
        guard let selectedConversationID else {
            return []
        }
        return messagesByConversation[selectedConversationID] ?? []
    }

    var canSend: Bool {
        !draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty && !isStreaming
    }

    func bootstrap() async {
        guard !didBootstrap else {
            return
        }
        didBootstrap = true

        do {
            try await refreshConversations(selecting: nil)
            statusLabel = "Ready"
        } catch {
            statusLabel = "Offline"
        }
    }

    func startNewConversation() {
        selectedConversationID = nil
        draft = ""
        statusLabel = "Ready"
    }

    func selectConversation(_ conversationID: String) async {
        selectedConversationID = conversationID
        if messagesByConversation[conversationID] == nil {
            await loadTranscript(for: conversationID)
        }
    }

    func sendDraft() async {
        let prompt = draft.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !prompt.isEmpty, !isStreaming else {
            return
        }

        draft = ""
        isStreaming = true
        statusLabel = "Thinking"

        do {
            let conversationID = try await ensureConversation(for: prompt)
            appendUserMessage(prompt, conversationID: conversationID)
            try await client.streamTurn(
                conversationID: conversationID,
                mode: mode,
                text: prompt,
            ) { [weak self] event in
                self?.handle(event)
            }
            try await refreshConversations(selecting: conversationID)
            statusLabel = "Ready"
        } catch {
            statusLabel = "Offline"
            if let conversationID = selectedConversationID {
                appendSystemMessage(error.localizedDescription, conversationID: conversationID)
            }
        }

        isStreaming = false
    }

    func resolveApproval(_ approval: ApprovalStateDTO, action: String) async {
        guard activeApprovalID == nil else {
            return
        }
        activeApprovalID = approval.id

        do {
            let updated = try await client.resolveApproval(id: approval.id, action: action)
            guard let conversationID = selectedConversationID else {
                activeApprovalID = nil
                return
            }
            updateMessages(for: conversationID) { messages in
                guard let index = messages.firstIndex(where: { $0.approval?.id == approval.id }) else {
                    return
                }
                messages[index].approval = updated
            }
            try await refreshConversations(selecting: conversationID)
        } catch {
            if let conversationID = selectedConversationID {
                appendSystemMessage(error.localizedDescription, conversationID: conversationID)
            }
        }

        activeApprovalID = nil
    }

    func presentVoicePlaceholder() {
        isShowingVoicePlaceholder = true
    }

    private func ensureConversation(for prompt: String) async throws -> String {
        if let selectedConversationID {
            if messagesByConversation[selectedConversationID] == nil {
                await loadTranscript(for: selectedConversationID)
            }
            return selectedConversationID
        }

        let conversation = try await client.createConversation(
            title: String(prompt.prefix(42)),
            mode: mode,
        )
        let summary = ConversationSummaryDTO(
            id: conversation.id,
            title: conversation.title,
            mode: conversation.mode,
            createdAt: conversation.createdAt,
            lastActivityAt: conversation.createdAt,
            lastMessagePreview: nil,
        )
        conversations.insert(summary, at: 0)
        selectedConversationID = conversation.id
        messagesByConversation[conversation.id] = []
        return conversation.id
    }

    private func refreshConversations(selecting conversationID: String?) async throws {
        let refreshed = try await client.listConversations()
        conversations = refreshed
        let targetConversationID = conversationID ?? selectedConversationID ?? refreshed.first?.id
        selectedConversationID = targetConversationID
        if let targetConversationID, messagesByConversation[targetConversationID] == nil {
            await loadTranscript(for: targetConversationID)
        }
    }

    private func loadTranscript(for conversationID: String) async {
        do {
            let transcript = try await client.listMessages(conversationID: conversationID)
            messagesByConversation[conversationID] = transcript.map {
                ChatMessage(
                    id: $0.id,
                    role: ChatMessage.Role(rawValue: $0.role) ?? .assistant,
                    content: $0.content,
                )
            }
        } catch {
            statusLabel = "Offline"
        }
    }

    private func appendUserMessage(_ text: String, conversationID: String) {
        updateMessages(for: conversationID) { messages in
            messages.append(
                ChatMessage(
                    id: "user-\(UUID().uuidString)",
                    role: .user,
                    content: text,
                )
            )
        }
    }

    private func appendSystemMessage(_ text: String, conversationID: String) {
        updateMessages(for: conversationID) { messages in
            messages.append(
                ChatMessage(
                    id: "system-\(UUID().uuidString)",
                    role: .system,
                    content: text,
                )
            )
        }
    }

    private func handle(_ event: ConversationStreamEvent) {
        switch event {
        case .assistantDelta(let conversationID, let turnID, let text):
            upsertAssistantMessage(turnID: turnID, conversationID: conversationID) { message in
                message.content += text
            }
        case .assistantCompleted(let conversationID, let turnID, let text):
            upsertAssistantMessage(turnID: turnID, conversationID: conversationID) { message in
                message.content = text
            }
        case .citationAdded(let conversationID, let turnID, let citation):
            upsertAssistantMessage(turnID: turnID, conversationID: conversationID) { message in
                if !message.citations.contains(citation) {
                    message.citations.append(citation)
                }
            }
        case .toolProposed(let conversationID, let turnID, let toolName):
            upsertAssistantMessage(turnID: turnID, conversationID: conversationID) { message in
                message.proposedToolName = toolName
            }
        case .approvalRequired(let conversationID, let turnID, let approval):
            upsertAssistantMessage(turnID: turnID, conversationID: conversationID) { message in
                message.approval = approval
            }
        case .warning(let conversationID, _, let text), .error(let conversationID, _, let text):
            appendSystemMessage(text, conversationID: conversationID)
        }
    }

    private func upsertAssistantMessage(
        turnID: String,
        conversationID: String,
        mutate: (inout ChatMessage) -> Void
    ) {
        updateMessages(for: conversationID) { messages in
            if let index = messages.firstIndex(where: { $0.id == "assistant-\(turnID)" }) {
                mutate(&messages[index])
                return
            }

            var message = ChatMessage(
                id: "assistant-\(turnID)",
                role: .assistant,
                content: "",
            )
            mutate(&message)
            messages.append(message)
        }
    }

    private func updateMessages(
        for conversationID: String,
        mutate: (inout [ChatMessage]) -> Void
    ) {
        var messages = messagesByConversation[conversationID] ?? []
        mutate(&messages)
        messagesByConversation[conversationID] = messages
    }
}
