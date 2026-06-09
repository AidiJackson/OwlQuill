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

export interface IdentityHealth {
  face: 'current' | 'stale';
  body: 'current' | 'stale';
  tattoos: 'current' | 'stale';
  slots: Record<string, { stale: boolean }>;
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
  identity_health?: IdentityHealth | null;
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

// ── Style Shops ───────────────────────────────────────────────────────

export type ShopType = 'barber' | 'tattoo' | 'mask' | 'jewellery' | 'weapon';
export type AttachmentMode = 'permanent' | 'removable';
export type StylePlacement = 'hair' | 'face' | 'lower_face' | 'right_arm' | 'left_arm' | 'chest' | 'back' | 'neck' | 'hand' | 'custom';
export type StyleElementStatus = 'active' | 'archived';

export interface StylePreset {
  id: number;
  shop_type: ShopType;
  name: string;
  slug: string;
  description: string;
  attachment_mode: AttachmentMode;
  placement: StylePlacement;
  prompt_token: string;
  preview_image_url?: string | null;
  is_active: boolean;
  sort_order: number;
  created_at: string;
}

export interface StyleElementRead {
  id: number;
  character_id: number;
  preset_id: number;
  placement: StylePlacement;
  status: StyleElementStatus;
  created_at: string;
  updated_at: string;
  preset: StylePreset;
}

export interface StyleElementsResponse {
  character_id: number;
  elements: StyleElementRead[];
}

// ── Body Canon ────────────────────────────────────────────────────────

export type MarkingType = 'tattoo' | 'scar' | 'burn' | 'birthmark';
export type MarkingAnchorStatus = 'missing' | 'generated' | 'locked';
export type MarkingPlacement =
  | 'left_upper_arm' | 'left_forearm' | 'left_full_arm'
  | 'right_upper_arm' | 'right_forearm' | 'right_full_arm'
  | 'chest' | 'upper_back' | 'lower_back' | 'full_back' | 'side' | 'ribs' | 'abdomen'
  | 'neck' | 'throat' | 'right_cheek' | 'left_cheek' | 'forehead' | 'chin' | 'jaw'
  | 'left_hand' | 'right_hand' | 'knuckles'
  | 'left_thigh' | 'right_thigh' | 'left_calf' | 'right_calf';

export type MarkingSize = 'small' | 'medium' | 'large' | 'full_sleeve' | 'full_back';

export interface BodyMarkingRead {
  id: string;
  type: MarkingType;
  placement: MarkingPlacement;
  style: string;
  size: MarkingSize;
  description: string;
  anchor_image_url: string | null;
  anchor_status: MarkingAnchorStatus;
  anchor_prompt: string | null;
  compact_token: string;
}

export interface BodyCanonRead {
  character_id: number;
  markings: BodyMarkingRead[];
}

export interface BodyAnchorResponse {
  character_id: number;
  marking: BodyMarkingRead;
}

// ── Body Identity Slots ───────────────────────────────────────────────

export type BodySlotKey = 'body_front' | 'body_three_quarter' | 'body_back' | 'tattoo_layout';
export type BodySlotStatus = 'missing' | 'generated' | 'locked';

export interface BodySlotEntry {
  key: BodySlotKey;
  label: string;
  url: string | null;
  status: BodySlotStatus;
  prompt: string | null;
}

export interface BodySlotsResponse {
  character_id: number;
  slots: BodySlotEntry[];
}

export type PackStageValue = 'missing' | 'partial' | 'locked';

export interface PackStages {
  face: PackStageValue;
  body: PackStageValue;
  marks: PackStageValue;
}

export interface CanonImportResponse {
  character_id: number;
  target_slot: string;
  url: string;
  image_id: number;
  pack_stages: PackStages;
}

// ─────────────────────────────────────────────────────────────────────

export interface PostMention {
  mention_text: string;
  target_type: 'user' | 'character' | 'unresolved';
  target_id?: number;
  display_name: string;
  url: string;
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
  source_type?: 'user' | 'ai_assisted' | 'ai_generated';
  image_url?: string;
  created_at: string;
  updated_at: string;
  mentions?: PostMention[];
}

export interface Notification {
  id: number;
  type: string;
  payload?: string;
  is_read: boolean;
  created_at: string;
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

export interface StorySpacePost {
  id: number;
  space_id: number;
  channel_id: number;
  author_user_id: number;
  author_username: string;
  character_id?: number;
  character_name?: string;
  character_avatar_url?: string;
  content: string;
  content_type: string;
  source_type?: 'user' | 'ai_assisted' | 'ai_generated';
  created_at: string;
  updated_at: string;
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

// Published Stories

export interface PublishedStorySegment {
  id: number;
  position: number;
  content: string;
  content_type: string;
  character_id?: number;
  character_name_snap?: string;
}

export interface PublishedStory {
  id: number;
  publisher_user_id: number;
  title: string;
  summary?: string;
  cover_url?: string;
  visibility: string;
  segment_count: number;
  segments: PublishedStorySegment[];
  published_at?: string;
  created_at: string;
  updated_at: string;
}

export interface PublishStoryPayload {
  title: string;
  summary?: string;
  cover_url?: string;
  post_ids: number[];
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

// RP Reply Generator
export type RPReplyResponseLength = 'short' | 'match' | 'long' | 'novella';
export type RPReplyStyleMatch = 'off' | 'soft' | 'strong';
export type RPReplyPerspective = 'first_person' | 'third_person_limited';
export type RPReplyFormatting = 'plain' | 'roleplay_bars';
export type RPReplyIntensity = 'standard' | 'mature' | 'explicit';
export type RPReplyHeatLevel = 'embers' | 'flame' | 'inferno';
export type RPStyleArchetype =
  | 'cinematic_dark_romance'
  | 'gothic_obsession'
  | 'slow_burn_tension'
  | 'dangerous_devotion'
  | 'primal_restraint';

export interface RPReplyRequest {
  partner_reply: string;
  instructions?: string;
  character_id?: number | null;
  story_id?: string | null;
  response_length: RPReplyResponseLength;
  style_match: RPReplyStyleMatch;
  perspective: RPReplyPerspective;
  formatting: RPReplyFormatting;
  intensity: RPReplyIntensity;
  heat_level: RPReplyHeatLevel;
  model_profile?: string | null;
  style_archetype?: RPStyleArchetype | null;
}

export interface RPReplyResponse {
  reply: string;
  warnings: string[];
  model_used: string;
  generation_time_ms: number;
  detected_stage: string;
  continuation_score: number;
  resolution_detected: boolean;
  pacing_warnings: string[];
  style_warnings: string[];
  // Internal dev mode diagnostics
  next_scene_goal?: string;
  repetition_score?: number;
  progression_success?: boolean;
  // Orchestration stabilization diagnostics (internal)
  ai_cadence_risk?: boolean;
  breath_gaze_density?: number;
  spatial_position?: string;
  spatial_dominance?: string;
  inferno_model_override?: boolean;
  resolved_heat?: string;
  // Beat planner diagnostics (internal dev mode)
  multi_beat_detected?: boolean;
  requested_beats?: string[];
  // Length profile diagnostics (internal dev mode)
  resolved_length_profile?: string;
  max_tokens_used?: number;
  requested_beat_count?: number;
  beat_completion_mode?: string;
  // Godmod output gate diagnostics
  godmod_detected?: boolean;
  godmod_severity?: string;
  godmod_warnings?: string[];
}

export interface RPModelOption {
  profile: string;
  label: string;
}

// ── RP Story Threads ──────────────────────────────────────────────────────────

export type RPPartnerPOV = 'first' | 'third' | 'unknown';
export type RPThreadStatus = 'active' | 'archived';
export type RPAuthorType = 'partner' | 'selected_character';

export interface RPStoryTurn {
  id: number;
  thread_id: number;
  turn_index: number;
  author_type: RPAuthorType;
  content: string;
  generated: boolean;
  godmod_detected?: boolean | null;
  godmod_severity?: string | null;
  metadata_json?: Record<string, unknown> | null;
  created_at: string;
}

export interface RPStoryThread {
  id: number;
  user_id: number;
  selected_character_id?: number | null;
  title: string;
  partner_label?: string | null;
  partner_pov: string;
  status: RPThreadStatus;
  summary_memory?: string | null;
  created_at: string;
  updated_at: string;
  turn_count: number;
}

export interface RPStoryThreadDetail extends RPStoryThread {
  turns: RPStoryTurn[];
}

export interface CreateRPStoryRequest {
  partner_starter: string;
  selected_character_id?: number | null;
  title?: string | null;
  partner_label?: string | null;
  partner_pov?: RPPartnerPOV;
  response_length?: string;
  style_match?: string;
  perspective?: string;
  formatting?: string;
  intensity?: string;
  heat_level?: string;
  instructions?: string | null;
}

export interface AddPartnerTurnRequest {
  content: string;
}

export interface GenerateThreadReplyRequest {
  instructions?: string | null;
  response_length?: string;
  style_match?: string;
  perspective?: string;
  formatting?: string;
  intensity?: string;
  heat_level?: string;
  style_archetype?: string | null;
  model_profile?: string | null;
}

export interface GenerateThreadReplyResponse {
  reply: string;
  model_used: string;
  generation_time_ms: number;
  godmod_detected: boolean;
  godmod_severity: string;
  godmod_warnings: string[];
  warnings: string[];
  continuation_score: number;
  pacing_warnings: string[];
  style_warnings: string[];
}

export interface SaveGeneratedTurnRequest {
  content: string;
  godmod_detected?: boolean | null;
  godmod_severity?: string | null;
  godmod_warnings?: string[] | null;
  model_used?: string | null;
  generation_time_ms?: number | null;
}

// ── 18+ Studio (Adult Studio) ─────────────────────────────────────────

export interface AdultStudioMarkRoute {
  canon_mark_id: string;
  region?: string | null;
  side?: string | null;
  route: string;
  reason?: string | null;
}

export interface AdultStudioStatus {
  character_id: number;
  // 6-value vocabulary from the new AdultIdentityModel system. 'preparing' is the
  // legacy/optimistic-only transient (kept so the UI's optimistic state still types).
  status: 'not_trained' | 'preparing' | 'prepared' | 'training' | 'ready' | 'stale' | 'failed';
  provider?: string | null;
  model_ref?: string | null;
  refs_count: number;
  marks_count: number;
  // ── Phase 2 additive fields ──
  canon_fingerprint?: string | null;
  stale?: boolean;
  active_version_id?: number | null;
  version_index?: number | null;
  marks?: AdultStudioMarkRoute[];
  training_enabled?: boolean;
  generation_enabled?: boolean;
}

export interface AdultStudioGenerateResult {
  image_url: string;
  provider: string;
  model_ref?: string | null;
  refs_count: number;
  used_refs: string[];
  multi_image_used: boolean;
  failure_reason?: string | null;
}

// Founder/admin-only Generate via the VALIDATED pipeline (active LoRA + enforcement
// plan + tattoo-enforcement executor) — NOT the OpenAI gpt-image path. Summer only.
export interface AdultStudioFounderRoute {
  route: string;
  status?: string;
  region?: string | null;
  side?: string | null;
  artifact_kind?: string | null;
  artifact_url?: string | null;
}

export interface AdultStudioFounderGenerateResult {
  final_image_url: string | null;
  intermediate_artifact_urls: string[];
  cost: number;
  runtime: number;
  routes_executed: AdultStudioFounderRoute[];
  manual_review_required: boolean;
  success: boolean;
  blocking_reasons: string[];
  orphaned_workers: string[];
}
