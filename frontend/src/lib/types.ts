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

// Profile types
export interface UserSummary {
  id: number;
  username: string;
  display_name?: string;
  avatar_url?: string;
}

export interface CharacterSummary {
  id: number;
  name: string;
  avatar_url?: string;
}

export interface RealmSummary {
  id: number;
  name: string;
  slug: string;
  tagline?: string;
}

export interface PostSummary {
  id: number;
  title?: string;
  content: string;
  content_type: string;
  created_at: string;
  realm?: RealmSummary;
  character?: CharacterSummary;
  author_user: UserSummary;
}

export interface UserProfile {
  id: number;
  username: string;
  display_name?: string;
  bio?: string;
  avatar_url?: string;
  created_at: string;
  follower_count: number;
  following_count: number;
  total_posts: number;
  joined_realms_count: number;
  recent_posts: PostSummary[];
}

export interface CharacterProfile {
  id: number;
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
  visibility: string;
  created_at: string;
  owner: UserSummary;
  posts_count: number;
  realms_count: number;
  recent_posts: PostSummary[];
}

// Discovery types
export interface UserSearchResult extends UserSummary {
  bio?: string;
  result_type: 'user';
}

export interface CharacterSearchResult extends CharacterSummary {
  short_bio?: string;
  owner_username?: string;
  result_type: 'character';
}

export interface RealmSearchResult extends RealmSummary {
  description?: string;
  owner_username?: string;
  is_public: boolean;
  result_type: 'realm';
}

export type SearchResult = UserSearchResult | CharacterSearchResult | RealmSearchResult;

export interface SearchResponse {
  results: SearchResult[];
  total: number;
}

// Analytics types
export interface AnalyticsEventCreate {
  event_type: string;
  payload?: Record<string, any>;
}
