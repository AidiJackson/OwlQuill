// API types matching backend schemas

export interface User {
  id: number;
  email: string;
  username: string;
  display_name?: string;
  bio?: string;
  avatar_url?: string;
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
  created_at: string;
  updated_at: string;
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
  created_at: string;
  updated_at: string;
}

export interface Post {
  id: number;
  realm_id?: number;
  author_user_id: number;
  character_id?: number;
  title?: string;
  content: string;
  content_type: 'ic' | 'ooc' | 'narration';
  created_at: string;
  updated_at: string;
}

export interface Comment {
  id: number;
  post_id: number;
  author_user_id: number;
  character_id?: number;
  content: string;
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

export interface Scene {
  id: number;
  title: string;
  description?: string;
  visibility: 'public' | 'unlisted' | 'private';
  created_by_user_id: number;
  created_at: string;
  updated_at: string;
}

export interface ScenePost {
  id: number;
  scene_id: number;
  author_user_id: number;
  character_id?: number;
  content: string;
  reply_to_id?: number;
  created_at: string;
}

export interface Block {
  id: number;
  blocker_id: number;
  blocked_id: number;
  created_at: string;
}

export interface Report {
  id: number;
  reporter_id: number;
  target_type: 'post' | 'scene_post';
  target_id: number;
  reason: 'harassment' | 'nsfw' | 'spam' | 'other';
  details?: string;
  status: 'open' | 'reviewed' | 'dismissed';
  created_at: string;
  updated_at: string;
}
