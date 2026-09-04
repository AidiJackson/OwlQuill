// API types matching backend schemas

export interface ActiveCharacterSummary {
  id: number;
  name: string;
  avatar_url?: string | null;
}

export interface User {
  id: number;
  email: string;
  username: string;
  display_name?: string;
  bio?: string;
  avatar_url?: string;
  cover_url?: string;
  is_admin?: boolean;
  is_seeder?: boolean;
  /** The character this account is currently "being" — its visible Ficshon
   *  identity. Null for multi-character accounts with no selection and for
   *  accounts with no characters (Wanderers). */
  active_character?: ActiveCharacterSummary | null;
  character_count?: number;
  /** True once the paid Writer Unlock is held. Founders/admins/seeders are
   *  exempt rather than unlocked, so this stays false for them. */
  writer_unlocked?: boolean;
  /** Server-authoritative mirror of the character-creation entitlement. */
  can_create_character?: boolean;
  /** When the public username may next be changed (rename cooldown), or null. */
  username_change_available_at?: string | null;
  /** When the account joined the Writer waitlist, or null if it has not.
   *  Interest only — it grants nothing and never affects entitlement. */
  writer_waitlist_joined_at?: string | null;
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
  /** True when a generated identity canon exists (even if not yet locked). */
  has_identity_canon?: boolean;
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

/** How a piece of text came to exist, decided server-side from evidence.
 *  The client can neither set nor influence it.
 *
 *  Three states are user-facing: written here, assisted by our AI, or created
 *  elsewhere. `unknown` is legacy only — rows that predate the system, shown as
 *  "Created elsewhere" like anything else Ficshon did not watch being created.
 *
 *  Deliberately a widened string union so the server can introduce a state
 *  without a coordinated client release. Anything unrecognised renders as no
 *  badge, which is the safe failure — an unlabelled post, never a wrong one. */
export type Provenance =
  | 'user_written'
  | 'ai_assisted'
  | 'external'
  | 'unknown'
  | (string & {});

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
  provenance?: Provenance;
  image_url?: string;
  created_at: string;
  updated_at: string;
  mentions?: PostMention[];
  /** Comment count, sent with the post so a collapsed comment section can show
   *  a truthful count before the comments themselves are fetched. */
  comment_count?: number;
}

/** Create payloads.
 *
 *  Explicit rather than `Partial<Post>` so there is no field here capable of
 *  asserting authorship. `composition_session_id` is evidence the server issued
 *  and can verify — it is not a verdict, and the server is free to ignore it.
 */
/** Editing-session counters. Integers only — this shape is the complete set of
 *  what a composer reports about how text arrived. There is deliberately no
 *  field here capable of carrying text. */
export interface CompositionMetrics {
  typed_chars: number;
  inserted_chars: number;
  internal_insert_chars: number;
  largest_insertion: number;
  insertion_count: number;
  edit_duration_ms: number;
}

export interface PostCreatePayload {
  content: string;
  title?: string;
  content_type?: 'ic' | 'ooc' | 'narration';
  post_kind?: 'general' | 'open_starter' | 'finished_piece';
  character_id?: number;
  image_url?: string;
  composition_session_id?: string;
}

export interface CommentCreatePayload {
  content: string;
  content_type?: 'ic' | 'ooc' | 'narration';
  character_id?: number;
  composition_session_id?: string;
}

export interface ScenePostCreatePayload {
  content: string;
  character_id?: number;
  reply_to_id?: number;
  composition_session_id?: string;
}

export interface SpacePostCreatePayload {
  content: string;
  content_type?: string;
  character_id?: number;
  composition_session_id?: string;
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
  /** Wanderer attribution — the public Wanderer username and account sigil.
   *  Both are absent on character-attributed (Writer) comments: a Writer's
   *  public output carries the character and nothing else. */
  author_username?: string;
  author_avatar_url?: string;
  character_id?: number;
  character_name?: string;
  character_avatar_url?: string;
  content: string;
  content_type?: 'ic' | 'ooc' | 'narration';
  provenance?: Provenance;
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
  provenance?: Provenance;
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

// ── Founder image workflow ────────────────────────────────────────────

// The server's account of what actually reached the provider. `warning` is set
// only when something the founder chose did NOT get sent.
export interface GenerationJobResult {
  refs_source: 'canon' | 'manual' | 'mixed' | 'none';
  refs_budget: number;
  canon_refs_sent: number;
  manual_refs_sent: number;
  manual_refs_dropped: number;
  refs_loaded: number;
  provider: string;
  manual_refs?: Array<{
    image_id: number;
    role: string;
    position: number;
    kind: string;
    sent: boolean;
    reason?: string;
  }>;
  warning?: string;
}

export interface ImageGenerationJob {
  job_id: string;
  character_id: number;
  status: 'queued' | 'running' | 'completed' | 'failed';
  stage?: string | null;
  progress_message?: string | null;
  attempt_count: number;
  created_at?: string | null;
  started_at?: string | null;
  finished_at?: string | null;
  error_code?: string | null;
  error_message?: string | null;
  // True when the submission was answered by an EXISTING job: nothing new was
  // started and nothing further was spent.
  reused: boolean;
  result?: GenerationJobResult | null;
  image?: LibraryImage | null;
}

// A character image as exposed to the PUBLIC — the curated gallery shape.
// ── Public Character Home ────────────────────────────────────────────
//
// Mirrors the backend's anonymous Character Home schemas EXACTLY. These are
// allowlists on the wire, so they are allowlists here: a field that is not in
// `schemas/character_home.py` must not be added below in the hope the server
// will start sending it.
//
// Everything is what an anonymous visitor receives, which is also what a
// signed-in visitor, the creator and an admin receive — the endpoints take no
// authentication dependency, so there is exactly one shape.

/** GET /characters/{id}/public-home */
export interface CharacterHomePublic {
  id: number;
  name: string;
  alias: string | null;
  role: string | null;
  era: string | null;
  species: string | null;
  short_bio: string | null;
  long_bio: string | null;
  tags: string | null;
  avatar_url: string | null;
  avatar_position_x: number | null;
  avatar_position_y: number | null;
  avatar_scale: number | null;
  cover_url: string | null;
  cover_position_x: number | null;
  cover_position_y: number | null;
  cover_scale: number | null;
}

/** GET /characters/{id}/public-home/posts */
export interface CharacterHomePostPublic {
  id: number;
  title: string | null;
  content: string;
  content_type: string;
  post_kind: string | null;
  provenance: string | null;
  created_at: string;
  image_url: string | null;
  realm_id: number;
  realm_name: string;
}

// Mirrors backend CharacterImagePublic: no prompt, provider, seed, metadata,
// status or visibility. The owner/admin variant is LibraryImage above.
export interface CharacterImagePublic {
  id: number;
  character_id: number;
  kind: string;
  url: string;
  created_at: string;
}

// What GET /characters/{id}/images actually returns — the endpoint is
// VIEWER-AWARE, so the shape depends on who is asking. Owners and admins get
// the working fields; everyone else gets CharacterImagePublic and nothing more.
//
// The owner-only fields are therefore OPTIONAL, and deliberately so: any code
// that wants a prompt or provider has to acknowledge it might not be there,
// which is exactly the question the server already answered. Do not "fix" this
// by widening them to required — that would let a component render a field the
// server never sent for a public viewer.
export type CharacterGalleryImage = CharacterImagePublic & {
  status?: string;
  visibility?: string;
  file_path?: string;
  provider?: string;
  prompt_summary?: string;
  seed?: string;
  metadata_json?: Record<string, unknown>;
};

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
  // Account username is never sent for Story Space posts — characters are the
  // only public identity; characterless posts render as an unlinked "Wanderer".
  character_id?: number;
  character_name?: string;
  character_avatar_url?: string;
  content: string;
  content_type: string;
  provenance?: Provenance;
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

// Sprint E9 — experimental Replicate img2img test (admin only). Pure image-to-image
// from a canon source image through Replicate; result is saved to the image library.
export interface ReplicateTestResult {
  image_url: string;
  provider: string;
  model_ref: string;
  source_role: string;
  source_image_url: string;
  prompt: string;
  strength: number;
  library_image_id?: number | null;
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

// Founder Async Lite (Sprint 13): fire-and-poll job snapshot. POST returns this with
// state=queued|running; GET reconciles it to completed (real RunPod 99_final) or failed.
export type AdultStudioFounderJobState = 'queued' | 'running' | 'completed' | 'failed';

export interface AdultStudioFounderJob {
  job_id: number;
  character_id: number;
  state: AdultStudioFounderJobState;
  run_id: string;
  final_image_url: string | null;
  intermediate_artifact_urls: string[];
  cost: number;
  runtime: number;
  routes_executed: AdultStudioFounderRoute[];
  manual_review_required: boolean;
  blocking_reasons: string[];
  orphaned_workers: string[];
  error?: string | null;
}

// ── Training Pack Review (S24W) — v4 LoRA candidate review (Summer-only) ──────
export type TrainingCandidateStatus = 'pending_review' | 'approved' | 'rejected' | 'failed';

export interface TrainingCandidate {
  role: string;
  group?: string | null;
  caption?: string | null;
  status: TrainingCandidateStatus;
  image?: string | null;
  error?: string | null;
}

export interface TrainingPackReview {
  character_id: number;
  review_state: string;
  counts: Record<string, number>;
  candidates: TrainingCandidate[];
}
