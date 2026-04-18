import Foundation

enum AssistantMode: String, Codable, CaseIterable, Identifiable {
    case general
    case field
    case research
    case medical

    var id: String { rawValue }

    var title: String {
        switch self {
        case .general:
            return "General"
        case .field:
            return "Field"
        case .research:
            return "Research"
        case .medical:
            return "Medical"
        }
    }
}

struct ConversationDTO: Codable, Identifiable {
    let id: String
    let title: String?
    let mode: AssistantMode
    let createdAt: Date

    enum CodingKeys: String, CodingKey {
        case id
        case title
        case mode
        case createdAt = "created_at"
    }
}

struct ConversationSummaryDTO: Codable, Identifiable {
    let id: String
    let title: String?
    let mode: AssistantMode
    let createdAt: Date
    let lastActivityAt: Date
    let lastMessagePreview: String?

    enum CodingKeys: String, CodingKey {
        case id
        case title
        case mode
        case createdAt = "created_at"
        case lastActivityAt = "last_activity_at"
        case lastMessagePreview = "last_message_preview"
    }
}

struct TranscriptMessageDTO: Codable, Identifiable {
    let id: String
    let role: String
    let content: String
    let createdAt: Date

    enum CodingKeys: String, CodingKey {
        case id
        case role
        case content
        case createdAt = "created_at"
    }
}

struct ConversationCreateRequestDTO: Encodable {
    let title: String?
    let mode: AssistantMode
}

struct ResponsePreferencesDTO: Encodable {
    let style: String
    let citations: Bool
    let audioReply: Bool

    enum CodingKeys: String, CodingKey {
        case style
        case citations
        case audioReply = "audio_reply"
    }
}

struct ConversationTurnRequestDTO: Encodable {
    let conversationID: String
    let mode: AssistantMode
    let text: String
    let assetIDs: [String]
    let enabledKnowledgePackIDs: [String]
    let responsePreferences: ResponsePreferencesDTO

    enum CodingKeys: String, CodingKey {
        case conversationID = "conversation_id"
        case mode
        case text
        case assetIDs = "asset_ids"
        case enabledKnowledgePackIDs = "enabled_knowledge_pack_ids"
        case responsePreferences = "response_preferences"
    }
}

struct SearchResultItemDTO: Codable, Identifiable, Hashable {
    let assetID: String
    let chunkID: String
    let label: String
    let excerpt: String
    let score: Double

    var id: String { chunkID }

    enum CodingKeys: String, CodingKey {
        case assetID = "asset_id"
        case chunkID = "chunk_id"
        case label
        case excerpt
        case score
    }
}

struct ApprovalDecisionRequestDTO: Encodable {
    let action: String
    let editedPayload: [String: String]

    enum CodingKeys: String, CodingKey {
        case action
        case editedPayload = "edited_payload"
    }
}

struct ApprovalStateDTO: Codable, Identifiable {
    let id: String
    let conversationID: String
    let turnID: String
    let toolName: String
    let reason: String
    let status: String
    let payload: [String: JSONValue]
    let result: [String: JSONValue]?

    enum CodingKeys: String, CodingKey {
        case id
        case conversationID = "conversation_id"
        case turnID = "turn_id"
        case toolName = "tool_name"
        case reason
        case status
        case payload
        case result
    }
}

enum JSONValue: Codable, Equatable {
    case string(String)
    case number(Double)
    case bool(Bool)
    case object([String: JSONValue])
    case array([JSONValue])
    case null

    init(from decoder: Decoder) throws {
        let container = try decoder.singleValueContainer()
        if container.decodeNil() {
            self = .null
        } else if let value = try? container.decode(Bool.self) {
            self = .bool(value)
        } else if let value = try? container.decode(Double.self) {
            self = .number(value)
        } else if let value = try? container.decode(String.self) {
            self = .string(value)
        } else if let value = try? container.decode([String: JSONValue].self) {
            self = .object(value)
        } else if let value = try? container.decode([JSONValue].self) {
            self = .array(value)
        } else {
            throw DecodingError.dataCorruptedError(
                in: container,
                debugDescription: "Unsupported JSON value.",
            )
        }
    }

    func encode(to encoder: Encoder) throws {
        var container = encoder.singleValueContainer()
        switch self {
        case .string(let value):
            try container.encode(value)
        case .number(let value):
            try container.encode(value)
        case .bool(let value):
            try container.encode(value)
        case .object(let value):
            try container.encode(value)
        case .array(let value):
            try container.encode(value)
        case .null:
            try container.encodeNil()
        }
    }

    var stringValue: String? {
        if case .string(let value) = self {
            return value
        }
        return nil
    }

    var objectValue: [String: JSONValue]? {
        if case .object(let value) = self {
            return value
        }
        return nil
    }

    fileprivate var anyValue: Any {
        switch self {
        case .string(let value):
            return value
        case .number(let value):
            return value
        case .bool(let value):
            return value
        case .object(let value):
            return value.mapValues(\.anyValue)
        case .array(let value):
            return value.map(\.anyValue)
        case .null:
            return NSNull()
        }
    }
}

extension Dictionary where Key == String, Value == JSONValue {
    func decoded<T: Decodable>(
        _ type: T.Type,
        using decoder: JSONDecoder = FieldAssistantAPIClient.makeDecoder(),
    ) throws -> T {
        let raw = mapValues(\.anyValue)
        let data = try JSONSerialization.data(withJSONObject: raw, options: [.sortedKeys])
        return try decoder.decode(type, from: data)
    }

    var prettyPrintedString: String {
        let raw = mapValues(\.anyValue)
        guard JSONSerialization.isValidJSONObject(raw),
              let data = try? JSONSerialization.data(withJSONObject: raw, options: [.prettyPrinted, .sortedKeys]),
              let string = String(data: data, encoding: .utf8)
        else {
            return "{}"
        }
        return string
    }
}

struct RawConversationStreamEventDTO: Decodable {
    let type: String
    let conversationID: String
    let turnID: String
    let payload: [String: JSONValue]

    enum CodingKeys: String, CodingKey {
        case type
        case conversationID = "conversation_id"
        case turnID = "turn_id"
        case payload
    }
}

enum ConversationStreamEvent {
    case assistantDelta(conversationID: String, turnID: String, text: String)
    case assistantCompleted(conversationID: String, turnID: String, text: String)
    case citationAdded(conversationID: String, turnID: String, citation: SearchResultItemDTO)
    case toolProposed(conversationID: String, turnID: String, toolName: String)
    case approvalRequired(conversationID: String, turnID: String, approval: ApprovalStateDTO)
    case warning(conversationID: String, turnID: String, text: String)
    case error(conversationID: String, turnID: String, text: String)
}

struct ChatMessage: Identifiable {
    enum Role: String {
        case user
        case assistant
        case system

        var title: String {
            switch self {
            case .user:
                return "You"
            case .assistant:
                return "Assistant"
            case .system:
                return "System"
            }
        }
    }

    let id: String
    var role: Role
    var content: String
    var citations: [SearchResultItemDTO] = []
    var proposedToolName: String?
    var approval: ApprovalStateDTO?
}
