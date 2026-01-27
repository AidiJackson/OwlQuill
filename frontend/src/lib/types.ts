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

// Monetization types
export interface PlanFeature {
  name: string;
  included: boolean;
  limit?: string;
}

export interface Plan {
  id: string;
  name: string;
  price_monthly: number | null;
  price_label: string;
  description: string;
  ai_credits_monthly: number;
  features: PlanFeature[];
  is_popular: boolean;
}

export interface CreditPack {
  id: string;
  name: string;
  credits: number;
  price_label: string;
}

export interface PlansResponse {
  plans: Plan[];
  payments_enabled: boolean;
  credit_packs: CreditPack[];
}

export interface CreditsResponse {
  balance: number;
  monthly_allowance: number;
  plan: string;
}
