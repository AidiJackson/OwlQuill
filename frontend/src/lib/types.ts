// API types matching backend schemas

export interface User {
  id: number;
  email: string;
  username: string;
  display_name?: string;
  bio?: string;
  avatar_url?: string;
  cover_url?: string;
  is_admin?: boolean;
  next_character_allowed_at?: string | null;
  created_at: string;
  updated_at: string;
}

export interface Character {
  id: number;
  owner_id: number;
  owner_username?: string;
  name: string;
  alias?: string;
  age?: string;
  species?: string;
  role?: string;
  era?: string;
  short_bio?: string;
  long_bio?: string;
  avatar_url?: string;
  cover_url?: string;
  cover_position_y?: number;
  cover_position_x?: number;
  cover_scale?: number;
  avatar_position_x?: number;
  avatar_position_y?: number;
  avatar_scale?: number;
  portrait_url?: string;
  tags?: string;
  visibility: 'public' | 'friends' | 'private';
  visual_locked?: boolean;
  identity_anchor_json?: string | null;
  created_at: string;
  updated_at: string;
}

export interface CharacterSearchResult {
  id: number;
  name: string;
  avatar_url?: string;
  cover_url?: string;
  cover_position_y?: number;
  cover_position_x?: number;
  cover_scale?: number;
  avatar_position_x?: number;
  avatar_position_y?: number;
  avatar_scale?: number;
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
  character_name?: string;
  character_avatar_url?: string;
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
  author_username?: string;
  character_id?: number;
  character_name?: string;
  character_avatar_url?: string;
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

// User images (profile covers, etc.)

export interface UserImageRead {
  id: number;
  user_id: number;
  kind: string;
  status: string;
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
  cover_url?: string;
  created_at: string;
}

export interface ProfileTimelineItem {
  type: 'post' | 'scene';
  created_at: string;
  realm_id?: number;
  realm_name?: string;
  payload: Record<string, unknown>;
}

// Story Spaces

export interface StorySpaceChannel {
  id: number;
  channel_type: string;
  name: string;
  position: number;
}

export interface StorySpaceListItem {
  id: number;
  owner_id: number;
  name: string;
  slug?: string;
  description?: string;
  cover_url?: string;
  your_role: string;
  member_count: number;
  created_at: string;
  updated_at: string;
}

export interface StorySpaceRead {
  id: number;
  owner_id: number;
  name: string;
  slug?: string;
  description?: string;
  cover_url?: string;
  your_role: string;
  member_count: number;
  channels: StorySpaceChannel[];
  created_at: string;
  updated_at: string;
}

// StoryLab story record
export interface StoryRecord {
  id: string;
  user_id: number;
  title: string;
  genre?: string | null;
  premise?: string | null;
  realm_id?: number | null;
  character_ids: number[];
  cover_color: string;
  created_at: string;
  updated_at: string;
}
