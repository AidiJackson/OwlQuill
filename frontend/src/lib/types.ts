// API types matching backend schemas

export interface User {
  id: number;
  email: string;
  username: string;
  display_name?: string;
  bio?: string;
  avatar_url?: string;
  next_character_allowed_at?: string | null;
  created_at: string;
  updated_at: string;
}

export interface Character {
  id: number;
  owner_id: number;
  name: string;
  alias?: string;
  age?: string;
  species?: string;
  role?: string;
  era?: string;
  short_bio?: string;
  long_bio?: string;
  avatar_url?: string;
  portrait_url?: string;
  tags?: string;
  visibility: 'public' | 'friends' | 'private';
  visual_locked?: boolean;
  created_at: string;
  updated_at: string;
}

export interface CharacterSearchResult {
  id: number;
  name: string;
  avatar_url?: string;
  short_bio?: string;
  species?: string;
  visibility?: 'public' | 'friends' | 'private';
}

export interface Realm {
  id: number;
  owner_id: number;
  name: string;
  slug: string;
  tagline?: string;
  description?: string;
  genre?: string;
  banner_url?: string;
  is_public: boolean;
  is_commons?: boolean;
  created_at: string;
  updated_at: string;
}

export interface Post {
  id: number;
  realm_id?: number;
  author_user_id: number;
  author_username?: string;
  character_id?: number;
  title?: string;
  content: string;
  content_type: 'ic' | 'ooc' | 'narration';
  post_kind?: 'general' | 'open_starter' | 'finished_piece';
  image_url?: string;
  created_at: string;
  updated_at: string;
}

export interface Comment {
  id: number;
  post_id: number;
  author_user_id: number;
  character_id?: number;
  content: string;
  content_type?: 'ic' | 'ooc' | 'narration';
  created_at: string;
  updated_at: string;
}

export interface Reaction {
  id: number;
  post_id: number;
  user_id: number;
  type: string;
  created_at: string;
}

export interface Token {
  access_token: string;
  token_type: string;
}

// Scenes
export type SceneVisibility = 'PUBLIC' | 'UNLISTED' | 'PRIVATE';

export interface Scene {
  id: number;
  realm_id?: number;
  title: string;
  description?: string;
  visibility: SceneVisibility;
  created_by_user_id: number;
  created_at: string;
  updated_at: string;
  post_count: number;
}

export interface ScenePost {
  id: number;
  scene_id: number;
  author_user_id: number;
  author_username?: string;
  character_id?: number;
  character_name?: string;
  content: string;
  reply_to_id?: number;
  created_at: string;
}

// Library images

export interface LibraryImage {
  id: number;
  character_id: number;
  kind: string;
  status: string;
  visibility: string;
  provider?: string;
  prompt_summary?: string;
  metadata_json?: Record<string, unknown>;
  file_path: string;
  url: string;
  created_at: string;
}

// Profile

export interface PublicUserProfile {
  id: number;
  username: string;
  display_name?: string;
  bio?: string;
  avatar_url?: string;
  created_at: string;
}

export interface ProfileTimelineItem {
  type: 'post' | 'scene';
  created_at: string;
  realm_id?: number;
  realm_name?: string;
  payload: Record<string, unknown>;
}
