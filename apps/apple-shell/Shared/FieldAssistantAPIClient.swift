import Foundation

struct FieldAssistantAPIClient {
    let baseURL: URL
    let session: URLSession
    private let decoder: JSONDecoder
    private let encoder: JSONEncoder

    init(
        baseURL: URL = URL(string: "http://127.0.0.1:8000")!,
        session: URLSession = .shared
    ) {
        self.baseURL = baseURL
        self.session = session
        self.decoder = Self.makeDecoder()
        self.encoder = JSONEncoder()
    }

    static func makeDecoder() -> JSONDecoder {
        let decoder = JSONDecoder()
        let formatterWithFractionalSeconds = ISO8601DateFormatter()
        formatterWithFractionalSeconds.formatOptions = [.withInternetDateTime, .withFractionalSeconds]

        let formatterWithoutFractionalSeconds = ISO8601DateFormatter()
        formatterWithoutFractionalSeconds.formatOptions = [.withInternetDateTime]

        decoder.dateDecodingStrategy = .custom { value in
            let container = try value.singleValueContainer()
            let string = try container.decode(String.self)
            if let date = formatterWithFractionalSeconds.date(from: string) {
                return date
            }
            if let date = formatterWithoutFractionalSeconds.date(from: string) {
                return date
            }
            throw DecodingError.dataCorruptedError(
                in: container,
                debugDescription: "Unsupported ISO-8601 date: \(string)",
            )
        }
        return decoder
    }

    func listConversations() async throws -> [ConversationSummaryDTO] {
        try await sendRequest(path: "/v1/conversations", method: "GET", body: Optional<String>.none)
    }

    func listMessages(conversationID: String) async throws -> [TranscriptMessageDTO] {
        try await sendRequest(
            path: "/v1/conversations/\(conversationID)/messages",
            method: "GET",
            body: Optional<String>.none,
        )
    }

    func createConversation(title: String?, mode: AssistantMode) async throws -> ConversationDTO {
        try await sendRequest(
            path: "/v1/conversations",
            method: "POST",
            body: ConversationCreateRequestDTO(title: title, mode: mode),
        )
    }

    func resolveApproval(id: String, action: String) async throws -> ApprovalStateDTO {
        try await sendRequest(
            path: "/v1/approvals/\(id)/decisions",
            method: "POST",
            body: ApprovalDecisionRequestDTO(action: action, editedPayload: [:]),
        )
    }

    func streamTurn(
        conversationID: String,
        mode: AssistantMode,
        text: String,
        onEvent: @escaping @MainActor (ConversationStreamEvent) -> Void
    ) async throws {
        let body = ConversationTurnRequestDTO(
            conversationID: conversationID,
            mode: mode,
            text: text,
            assetIDs: [],
            enabledKnowledgePackIDs: [],
            responsePreferences: ResponsePreferencesDTO(
                style: "concise",
                citations: true,
                audioReply: false,
            ),
        )
        let request = try makeRequest(
            path: "/v1/conversations/\(conversationID)/turns",
            method: "POST",
            body: body,
        )
        let (bytes, response) = try await session.bytes(for: request)
        try validate(response: response)

        for try await line in bytes.lines {
            let trimmed = line.trimmingCharacters(in: .whitespacesAndNewlines)
            if trimmed.isEmpty {
                continue
            }
            let event = try parseStreamEvent(from: trimmed)
            await onEvent(event)
        }
    }

    private func sendRequest<Response: Decodable, Body: Encodable>(
        path: String,
        method: String,
        body: Body?
    ) async throws -> Response {
        let request = try makeRequest(path: path, method: method, body: body)
        let (data, response) = try await session.data(for: request)
        try validate(response: response, data: data)
        return try decoder.decode(Response.self, from: data)
    }

    private func makeRequest<Body: Encodable>(
        path: String,
        method: String,
        body: Body?
    ) throws -> URLRequest {
        let url = baseURL.appending(path: path)
        var request = URLRequest(url: url)
        request.httpMethod = method
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue("application/json", forHTTPHeaderField: "Accept")

        if let body {
            request.httpBody = try encoder.encode(body)
        }

        return request
    }

    private func validate(response: URLResponse, data: Data? = nil) throws {
        guard let httpResponse = response as? HTTPURLResponse else {
            throw FieldAssistantClientError.invalidResponse
        }

        guard (200...299).contains(httpResponse.statusCode) else {
            let message: String
            if let data, let text = String(data: data, encoding: .utf8), !text.isEmpty {
                message = text
            } else {
                message = "HTTP \(httpResponse.statusCode)"
            }
            throw FieldAssistantClientError.httpFailure(message)
        }
    }

    private func parseStreamEvent(from line: String) throws -> ConversationStreamEvent {
        let raw = try decoder.decode(RawConversationStreamEventDTO.self, from: Data(line.utf8))
        switch raw.type {
        case "assistant.delta":
            return .assistantDelta(
                conversationID: raw.conversationID,
                turnID: raw.turnID,
                text: raw.payload["text"]?.stringValue ?? "",
            )
        case "assistant.message.completed":
            return .assistantCompleted(
                conversationID: raw.conversationID,
                turnID: raw.turnID,
                text: raw.payload["text"]?.stringValue ?? "",
            )
        case "citation.added":
            return .citationAdded(
                conversationID: raw.conversationID,
                turnID: raw.turnID,
                citation: try raw.payload.decoded(SearchResultItemDTO.self, using: decoder),
            )
        case "tool.proposed":
            return .toolProposed(
                conversationID: raw.conversationID,
                turnID: raw.turnID,
                toolName: raw.payload["tool_name"]?.stringValue ?? "tool",
            )
        case "approval.required":
            return .approvalRequired(
                conversationID: raw.conversationID,
                turnID: raw.turnID,
                approval: try raw.payload.decoded(ApprovalStateDTO.self, using: decoder),
            )
        case "warning":
            return .warning(
                conversationID: raw.conversationID,
                turnID: raw.turnID,
                text: raw.payload["text"]?.stringValue ?? "Warning",
            )
        case "error":
            return .error(
                conversationID: raw.conversationID,
                turnID: raw.turnID,
                text: raw.payload["text"]?.stringValue ?? "Error",
            )
        default:
            return .warning(
                conversationID: raw.conversationID,
                turnID: raw.turnID,
                text: "Unhandled event: \(raw.type)",
            )
        }
    }
}

enum FieldAssistantClientError: LocalizedError {
    case invalidResponse
    case httpFailure(String)

    var errorDescription: String? {
        switch self {
        case .invalidResponse:
            return "The local engine returned an invalid response."
        case .httpFailure(let message):
            return message
        }
    }
}
