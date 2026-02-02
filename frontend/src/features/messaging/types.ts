export interface CharacterSummary {
  id: number;
  name: string;
  avatar_url?: string;
}

export interface MessageRead {
  id: number;
  sender_character_id: number;
  body: string;
  created_at: string;
}

export interface ConversationRead {
  id: number;
  character_a: CharacterSummary;
  character_b: CharacterSummary;
  last_message?: MessageRead;
  updated_at: string;
}
