import { rateLimitMessage } from './rateLimit';
import type { User, Character, CharacterSearchResult, Realm, Post, Comment, Reaction, Token, Scene, ScenePost, ProfileTimelineItem, LibraryImage, CharacterGalleryImage, UserImageRead, StoryRecord, StorySpaceListItem, StorySpaceRead, StorySpacePost, PublishedStory, PublishStoryPayload, RPReplyRequest, RPReplyResponse, Notification, StylePreset, StyleElementsResponse, BodyCanonRead, BodyAnchorResponse, BodySlotsResponse, CanonImportResponse, RPStoryThread, RPStoryThreadDetail, RPStoryTurn, CreateRPStoryRequest, AddPartnerTurnRequest, GenerateThreadReplyRequest, GenerateThreadReplyResponse, SaveGeneratedTurnRequest, AdultStudioStatus, AdultStudioGenerateResult, AdultStudioFounderJob, ReplicateTestResult, TrainingPackReview, TrainingCandidate, TrainingCandidateStatus, PostCreatePayload, CommentCreatePayload, ScenePostCreatePayload, SpacePostCreatePayload, CompositionMetrics, ImageGenerationJob, CharacterHomePublic, CharacterHomePostPublic, CharacterImagePublic } from './types';

// Use Vite proxy (/api) by default in dev, or custom URL from env
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || '/api';

class ApiClient {
  private getToken(): string | null {
    return localStorage.getItem('token');
  }

  private setToken(token: string): void {
    localStorage.setItem('token', token);
  }

  private clearToken(): void {
    localStorage.removeItem('token');
  }

  /**
   * Is a token persisted for this browser?
   *
   * The auth store needs this synchronously, before any request is made, to
   * tell "we have not checked yet" from "there is nothing to check". It asks
   * here rather than reading localStorage itself so the storage key stays
   * owned by one module.
   */
  hasToken(): boolean {
    return !!this.getToken();
  }

  private async request<T>(
    endpoint: string,
    options: RequestInit = {}
  ): Promise<T> {
    const token = this.getToken();
    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
      ...(options.headers as Record<string, string>),
    };

    if (token) {
      headers['Authorization'] = `Bearer ${token}`;
    }

    const response = await fetch(`${API_BASE_URL}${endpoint}`, {
      ...options,
      headers,
      credentials: 'include',
    });

    if (!response.ok) {
      if (response.status === 429) {
        // Throttling is the one status a user is likely to meet head-on, so it
        // never falls through to the bare `HTTP ${status}` branch below.
        const throttled = await response.json().catch(() => null);
        throw new Error(
          rateLimitMessage((throttled as { detail?: unknown } | null)?.detail)
        );
      }
      const error = await response.json().catch(() => ({ detail: 'An error occurred' }));
      throw new Error(error.detail || `HTTP ${response.status}`);
    }

    if (response.status === 204) {
      return null as T;
    }

    return response.json();
  }

  // Auth
  async register(email: string, username: string, password: string, inviteCode: string): Promise<User> {
    return this.request<User>('/auth/register', {
      method: 'POST',
      body: JSON.stringify({ email, username, password, invite_code: inviteCode }),
    });
  }

  async login(email: string, password: string): Promise<Token> {
    const token = await this.request<Token>('/auth/login', {
      method: 'POST',
      body: JSON.stringify({ email, password }),
    });
    this.setToken(token.access_token);
    return token;
  }

  logout(): void {
    this.clearToken();
  }

  async getMe(): Promise<User> {
    return this.request<User>('/auth/me');
  }

  async forgotPassword(email: string): Promise<{ message: string; reset_url?: string }> {
    return this.request<{ message: string; reset_url?: string }>('/auth/forgot-password', {
      method: 'POST',
      body: JSON.stringify({ email }),
    });
  }

  async resetPassword(token: string, new_password: string): Promise<{ message: string }> {
    return this.request<{ message: string }>('/auth/reset-password', {
      method: 'POST',
      body: JSON.stringify({ token, new_password }),
    });
  }

  // Users
  async updateMe(data: { display_name?: string; bio?: string; avatar_url?: string }): Promise<User> {
    return this.request<User>('/users/me', {
      method: 'PATCH',
      body: JSON.stringify(data),
    });
  }

  /** Change the account's public (Wanderer) username. Validation, uniqueness
   *  and the rename cooldown are enforced server-side; errors surface as the
   *  API's own message so the user sees why. */
  async updateMyUsername(username: string): Promise<User> {
    return this.request<User>('/users/me/username', {
      method: 'PATCH',
      body: JSON.stringify({ username }),
    });
  }

  /** Register interest in the Writer Unlock. Idempotent, and grants nothing —
   *  the returned user still has `writer_unlocked: false`. */
  async joinWriterWaitlist(): Promise<User> {
    return this.request<User>('/users/me/writer-waitlist', { method: 'POST' });
  }

  /** Withdraw from the Writer waitlist. Idempotent. */
  async leaveWriterWaitlist(): Promise<User> {
    return this.request<User>('/users/me/writer-waitlist', { method: 'DELETE' });
  }

  // Active character (the account's visible Ficshon identity)
  async setActiveCharacter(characterId: number | null): Promise<User> {
    return this.request<User>('/users/me/active-character', {
      method: 'PATCH',
      body: JSON.stringify({ character_id: characterId }),
    });
  }

  // Characters
  async getCharacters(): Promise<Character[]> {
    return this.request<Character[]>('/characters/');
  }

  async getCharacterPosts(characterId: number, limit = 20): Promise<ProfileTimelineItem[]> {
    return this.request<ProfileTimelineItem[]>(`/characters/${characterId}/posts?limit=${limit}`);
  }

  async getCharacterMentions(characterId: number, limit = 20): Promise<ProfileTimelineItem[]> {
    return this.request<ProfileTimelineItem[]>(`/characters/${characterId}/mentions?limit=${limit}`);
  }

  async getCharacterDirectory(limit = 30, skip = 0): Promise<CharacterSearchResult[]> {
    return this.request<CharacterSearchResult[]>(`/characters/directory?limit=${limit}&skip=${skip}`);
  }

  async searchCharacters(q: string): Promise<CharacterSearchResult[]> {
    return this.request<CharacterSearchResult[]>(`/characters/search?q=${encodeURIComponent(q)}`);
  }

  async createCharacter(data: Partial<Character>): Promise<Character> {
    return this.request<Character>('/characters/', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  }

  async getCharacter(id: number): Promise<Character> {
    return this.request<Character>(`/characters/${id}`);
  }

  async updateCharacter(id: number, data: Partial<Character>): Promise<Character> {
    return this.request<Character>(`/characters/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(data),
    });
  }

  async deleteCharacter(id: number): Promise<void> {
    return this.request<void>(`/characters/${id}`, {
      method: 'DELETE',
    });
  }

  // Realms
  async getRealms(search?: string, publicOnly = true): Promise<Realm[]> {
    const params = new URLSearchParams();
    if (search) params.append('search', search);
    params.append('public_only', publicOnly.toString());
    return this.request<Realm[]>(`/realms/?${params}`);
  }

  async createRealm(data: Partial<Realm>): Promise<Realm> {
    return this.request<Realm>('/realms/', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  }

  async getRealm(id: number): Promise<Realm> {
    return this.request<Realm>(`/realms/${id}`);
  }

  async joinRealm(id: number): Promise<void> {
    return this.request<void>(`/realms/${id}/join`, {
      method: 'POST',
    });
  }

  // Posts
  async getFeed(skip = 0, limit = 50): Promise<Post[]> {
    return this.request<Post[]>(`/posts/feed?skip=${skip}&limit=${limit}`);
  }

  async getRealmPosts(realmId: number, skip = 0, limit = 50): Promise<Post[]> {
    return this.request<Post[]>(`/posts/realms/${realmId}/posts?skip=${skip}&limit=${limit}`);
  }

  async createPost(realmId: number, data: PostCreatePayload): Promise<Post> {
    return this.request<Post>(`/posts/realms/${realmId}/posts`, {
      method: 'POST',
      body: JSON.stringify(data),
    });
  }

  async getPost(id: number): Promise<Post> {
    return this.request<Post>(`/posts/${id}`);
  }

  async deletePost(id: number): Promise<void> {
    return this.request<void>(`/posts/${id}`, { method: 'DELETE' });
  }

  // Comments
  async getPostComments(postId: number): Promise<Comment[]> {
    return this.request<Comment[]>(`/comments/posts/${postId}/comments`);
  }

  async createComment(postId: number, data: CommentCreatePayload): Promise<Comment> {
    return this.request<Comment>(`/comments/posts/${postId}/comments`, {
      method: 'POST',
      body: JSON.stringify(data),
    });
  }

  // Reactions
  async getPostReactions(postId: number): Promise<Reaction[]> {
    return this.request<Reaction[]>(`/reactions/posts/${postId}/reactions`);
  }

  async addReaction(postId: number, type: string): Promise<Reaction> {
    return this.request<Reaction>(`/reactions/posts/${postId}/reactions`, {
      method: 'POST',
      body: JSON.stringify({ type }),
    });
  }

  async deleteReaction(reactionId: number): Promise<void> {
    return this.request<void>(`/reactions/${reactionId}`, {
      method: 'DELETE',
    });
  }

  // Scenes
  async listScenes(realmId: number): Promise<Scene[]> {
    return this.request<Scene[]>(`/scenes/?realm_id=${realmId}`);
  }

  async createScene(data: { realm_id: number; title: string; description?: string; visibility?: string }): Promise<Scene> {
    return this.request<Scene>('/scenes/', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  }

  async getScene(sceneId: number): Promise<Scene> {
    return this.request<Scene>(`/scenes/${sceneId}`);
  }

  async listScenePosts(sceneId: number): Promise<ScenePost[]> {
    return this.request<ScenePost[]>(`/scenes/${sceneId}/posts`);
  }

  async createScenePost(sceneId: number, data: ScenePostCreatePayload): Promise<ScenePost> {
    return this.request<ScenePost>(`/scenes/${sceneId}/posts`, {
      method: 'POST',
      body: JSON.stringify(data),
    });
  }

  // AI
  async generateCharacterBio(
    name: string,
    species?: string,
    role?: string,
    era?: string,
    tags: string[] = []
  ): Promise<{ short_bio: string; long_bio: string }> {
    return this.request('/ai/character-bio', {
      method: 'POST',
      body: JSON.stringify({ name, species, role, era, tags }),
    });
  }

  async generateScene(characters: string[], setting: string, mood?: string, prompt = ''): Promise<{ scene: string; dialogue: string }> {
    return this.request('/ai/scene', {
      method: 'POST',
      body: JSON.stringify({ characters, setting, mood, prompt }),
    });
  }

  // Image library — user-scoped. All options are additive; calling with no
  // args preserves the original whole-archive behaviour.
  async listMyCharacterImages(opts?: {
    characterId?: number;
    kind?: string[];
    sort?: 'newest' | 'oldest';
    limit?: number;
    offset?: number;
  }): Promise<LibraryImage[]> {
    const params = new URLSearchParams();
    if (opts?.characterId != null) params.set('character_id', String(opts.characterId));
    if (opts?.kind) opts.kind.forEach((k) => params.append('kind', k));
    if (opts?.sort) params.set('sort', opts.sort);
    if (opts?.limit != null) params.set('limit', String(opts.limit));
    if (opts?.offset != null) params.set('offset', String(opts.offset));
    const qs = params.toString();
    return this.request<LibraryImage[]>(`/users/me/character-images${qs ? `?${qs}` : ''}`);
  }

  // A character's images as the server chooses to expose them to this viewer:
  // the full working set for the owner/admin, the curated public gallery for
  // everyone else. The endpoint decides — the client never asks for "public",
  // so there is no client-side flag to get wrong.
  async listCharacterImages(characterId: number): Promise<CharacterGalleryImage[]> {
    return this.request<CharacterGalleryImage[]>(`/characters/${characterId}/images`);
  }

  // ── Public Character Home ──────────────────────────────────────────
  //
  // The only endpoints in the client that answer without credentials. They are
  // grouped and named `public…` so that fact is visible at the call site.
  //
  // `request()` still attaches the bearer token when one exists; that is
  // harmless and deliberate — the endpoints take no authentication dependency,
  // so the response is identical with or without it. The public Character Home
  // must never branch on the viewer, and this is the client half of that.
  //
  // A rejected promise here means 404 (the character has no public Home —
  // unpublished, private, or nonexistent, deliberately indistinguishable) or a
  // transport failure. The caller decides which state to render.

  async getPublicCharacterHome(characterId: number): Promise<CharacterHomePublic> {
    return this.request<CharacterHomePublic>(`/characters/${characterId}/public-home`);
  }

  async getPublicCharacterHomePosts(
    characterId: number,
    limit = 20,
  ): Promise<CharacterHomePostPublic[]> {
    return this.request<CharacterHomePostPublic[]>(
      `/characters/${characterId}/public-home/posts?limit=${limit}`,
    );
  }

  async getPublicCharacterHomeImages(
    characterId: number,
    limit = 24,
  ): Promise<CharacterImagePublic[]> {
    return this.request<CharacterImagePublic[]>(
      `/characters/${characterId}/public-home/images?limit=${limit}`,
    );
  }

  async setAvatar(imageType: 'character' | 'user', imageId: number): Promise<{ avatar_url: string }> {
    return this.request<{ avatar_url: string }>('/users/me/avatar', {
      method: 'POST',
      body: JSON.stringify({ image_type: imageType, image_id: imageId }),
    });
  }

  async setCharacterAvatar(characterId: number, imageType: 'character' | 'user', imageId: number): Promise<{ avatar_url: string }> {
    return this.request<{ avatar_url: string }>(`/characters/${characterId}/avatar`, {
      method: 'POST',
      body: JSON.stringify({ image_type: imageType, image_id: imageId }),
    });
  }

  async setCharacterCover(characterId: number, imageType: 'character' | 'user', imageId: number, coverPositionY = 0.5, coverPositionX = 0.5): Promise<{ cover_url: string; cover_position_y: number; cover_position_x: number }> {
    return this.request<{ cover_url: string; cover_position_y: number; cover_position_x: number }>(`/characters/${characterId}/cover`, {
      method: 'POST',
      body: JSON.stringify({ image_type: imageType, image_id: imageId, cover_position_y: coverPositionY, cover_position_x: coverPositionX }),
    });
  }

  async setMyProfileCover(imageId: number): Promise<{ cover_url: string; image_id: number }> {
    return this.request<{ cover_url: string; image_id: number }>(`/users/me/images/${imageId}/set-cover`, {
      method: 'POST',
    });
  }

  async listMyUserImages(kind?: string): Promise<UserImageRead[]> {
    const qs = kind ? `?kind=${encodeURIComponent(kind)}` : '';
    return this.request<UserImageRead[]>(`/users/me/images${qs}`);
  }

  // Image quota (B22)
  async getImageQuota(): Promise<{ used: number; limit: number | null; remaining: number | null; unlimited: boolean; reset_in_seconds: number | null; reset_at: string | null }> {
    return this.request('/images/quota');
  }

  // Images library (legacy)
  async listLibraryImages(): Promise<LibraryImage[]> {
    return this.request<LibraryImage[]>('/images/');
  }

  async generateLibraryImage(prompt: string): Promise<LibraryImage> {
    return this.request<LibraryImage>('/images/generate', {
      method: 'POST',
      body: JSON.stringify({ prompt }),
    });
  }

  async deleteCharacterImage(characterId: number, imageId: number): Promise<void> {
    return this.request<void>(`/characters/${characterId}/images/${imageId}`, {
      method: 'DELETE',
    });
  }

  /**
   * "What the model receives" for one feature reference.
   *
   * Re-derives the isolated representation on the server using the SAME
   * transform generation uses — nothing is stored, so this cannot drift from
   * what is actually sent, and no second copy of anyone's photograph exists.
   *
   * Returns an object URL the caller MUST revoke; the response is an image, not
   * JSON, so it bypasses `request()`.
   */
  async fetchIsolatedReference(
    characterId: number,
    imageId: number,
    role: string,
  ): Promise<string> {
    const token = this.getToken();
    const response = await fetch(
      `${API_BASE_URL}/characters/${characterId}/image-generator/references/${imageId}` +
        `/isolated?role=${encodeURIComponent(role)}`,
      {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
        credentials: 'include',
      },
    );
    if (!response.ok) {
      // The server's refusal text names what to do about it ("Use a clear
      // front-facing photo…"), so it is surfaced rather than replaced.
      const body = await response.json().catch(() => null);
      throw new Error(body?.detail || 'Could not isolate this reference.');
    }
    return URL.createObjectURL(await response.blob());
  }

  // ── Founder image workflow ──────────────────────────────────────────

  // Upload an image from this device as PRIVATE character media (kind=uploaded).
  // Founder/seeder only — the server is the gate; hiding the button is not.
  // The result is a reference, not gallery or post material.
  async uploadCharacterImage(
    characterId: number,
    file: File,
    note?: string,
  ): Promise<LibraryImage> {
    const form = new FormData();
    form.append('file', file);
    if (note) form.append('note', note);
    const token = this.getToken();
    // Not this.request(): a multipart body must NOT carry an explicit
    // Content-Type — the browser sets it with the boundary.
    const response = await fetch(`${API_BASE_URL}/characters/${characterId}/images/upload`, {
      method: 'POST',
      headers: token ? { Authorization: `Bearer ${token}` } : {},
      body: form,
      credentials: 'include',
    });
    if (!response.ok) {
      const error = await response.json().catch(() => ({ detail: 'Upload failed' }));
      throw new Error(error.detail || `HTTP ${response.status}`);
    }
    return response.json();
  }

  // Submit ONE generation intent. `idempotencyKey` identifies the intent, not
  // the request: resending it (double-tap, retry, reconnect) returns the SAME
  // job with reused=true and spends nothing further. Mint a new key only when
  // the founder genuinely wants another image.
  async submitImageGenerationJob(
    characterId: number,
    payload: {
      prompt: string;
      include_character: boolean;
      provider_option: string;
      is_cover?: boolean;
      reference_image_ids?: number[];
      reference_roles?: string[];
      // Omitted by the Image Generator; the server defaults to "augment".
      reference_mode?: 'augment' | 'deliberate';
      idempotency_key: string;
    },
  ): Promise<ImageGenerationJob> {
    return this.request<ImageGenerationJob>(
      `/characters/${characterId}/image-generator/jobs`,
      { method: 'POST', body: JSON.stringify(payload) },
    );
  }

  async getImageGenerationJob(characterId: number, jobId: string): Promise<ImageGenerationJob> {
    return this.request<ImageGenerationJob>(
      `/characters/${characterId}/image-generator/jobs/${jobId}`,
    );
  }

  // Refresh recovery: re-attach to the latest generation this account started
  // for the character, without submitting anything.
  async getLatestImageGenerationJob(
    characterId: number,
  ): Promise<{ job: ImageGenerationJob | null }> {
    return this.request<{ job: ImageGenerationJob | null }>(
      `/characters/${characterId}/image-generator/jobs/latest`,
    );
  }

  async saveIdentityAccessory(
    characterId: number,
    payload: { type: string; name: string; description: string; visual_rules?: string[] },
  ): Promise<{ character_id: number; accessories: Array<Record<string, unknown>> }> {
    return this.request(`/characters/${characterId}/identity-accessory`, {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  }

  async generateAccessoryAnchor(
    characterId: number,
    accessoryId: string,
  ): Promise<{ character_id: number; accessory: Record<string, unknown> }> {
    return this.request(`/characters/${characterId}/identity-accessory/generate-anchor`, {
      method: 'POST',
      body: JSON.stringify({ accessory_id: accessoryId }),
    });
  }

  async lockAccessoryAnchor(
    characterId: number,
    accessoryId: string,
  ): Promise<{ character_id: number; accessory: Record<string, unknown> }> {
    return this.request(`/characters/${characterId}/identity-accessory/lock-anchor`, {
      method: 'POST',
      body: JSON.stringify({ accessory_id: accessoryId }),
    });
  }

  async generateFitAnchor(
    characterId: number,
    accessoryId: string,
  ): Promise<{ character_id: number; accessory: Record<string, unknown> }> {
    return this.request(`/characters/${characterId}/identity-accessory/generate-fit-anchor`, {
      method: 'POST',
      body: JSON.stringify({ accessory_id: accessoryId }),
    });
  }

  async lockFitAnchor(
    characterId: number,
    accessoryId: string,
  ): Promise<{ character_id: number; accessory: Record<string, unknown> }> {
    return this.request(`/characters/${characterId}/identity-accessory/lock-fit-anchor`, {
      method: 'POST',
      body: JSON.stringify({ accessory_id: accessoryId }),
    });
  }

  // ── Candidate slot replacement (Identity Evolution Phase 2) ──────────────────

  async createCandidateSlot(
    characterId: number,
    payload: { slot: string; image_url: string },
  ): Promise<{
    id: number; character_id: number; slot: string; image_url: string;
    status: string; validation_status: string; validation_notes: string | null; created_at: string;
  }> {
    return this.request(`/characters/${characterId}/identity-evolution/candidate-slot`, {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  }

  async validateCandidateSlot(
    characterId: number,
    candidateId: number,
  ): Promise<{
    id: number; character_id: number; slot: string; image_url: string;
    status: string; validation_status: string; validation_notes: string | null; created_at: string;
  }> {
    return this.request(
      `/characters/${characterId}/identity-evolution/candidate-slot/${candidateId}/validate`,
      { method: 'POST' },
    );
  }

  async promoteCandidateSlot(
    characterId: number,
    candidateId: number,
  ): Promise<{
    snapshot: { id: number; character_id: number; snapshot_version: number; anchor_version: number; reason: string | null; created_at: string };
    candidate: { id: number; character_id: number; slot: string; image_url: string; status: string; validation_status: string; validation_notes: string | null; created_at: string };
  }> {
    return this.request(
      `/characters/${characterId}/identity-evolution/candidate-slot/${candidateId}/promote`,
      { method: 'POST' },
    );
  }

  async rejectCandidateSlot(
    characterId: number,
    candidateId: number,
  ): Promise<{
    id: number; character_id: number; slot: string; image_url: string;
    status: string; validation_status: string; validation_notes: string | null; created_at: string;
  }> {
    return this.request(
      `/characters/${characterId}/identity-evolution/candidate-slot/${candidateId}/reject`,
      { method: 'POST' },
    );
  }

  async submitReport(targetType: string, targetId: string, reason: string, detail?: string): Promise<{ id: number }> {
    return this.request<{ id: number }>('/reports', {
      method: 'POST',
      body: JSON.stringify({ target_type: targetType, target_id: targetId, reason, detail }),
    });
  }

  // RP Reply Generator
  async generateRPReply(data: RPReplyRequest): Promise<RPReplyResponse> {
    return this.request<RPReplyResponse>('/storylab/rp-reply/generate', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  }

  // StoryLab stories
  async createStory(data: {
    title: string;
    genre?: string;
    premise?: string;
    realm_id?: number | null;
    character_ids?: number[];
    cover_color?: string;
  }): Promise<StoryRecord> {
    return this.request<StoryRecord>('/storylab/stories', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  }

  async listStories(): Promise<StoryRecord[]> {
    return this.request<StoryRecord[]>('/storylab/stories');
  }

  async getStory(storyId: string): Promise<StoryRecord> {
    return this.request<StoryRecord>(`/storylab/stories/${encodeURIComponent(storyId)}`);
  }

  // Story Spaces
  async getStorySpaces(): Promise<StorySpaceListItem[]> {
    return this.request<StorySpaceListItem[]>('/story-spaces/');
  }

  async createStorySpace(data: { name: string; description?: string; slug?: string; cover_url?: string }): Promise<StorySpaceRead> {
    return this.request<StorySpaceRead>('/story-spaces/', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  }

  async getStorySpace(id: number): Promise<StorySpaceRead> {
    return this.request<StorySpaceRead>(`/story-spaces/${id}`);
  }

  async getSpacePosts(spaceId: number, channelId: number): Promise<StorySpacePost[]> {
    return this.request<StorySpacePost[]>(`/story-spaces/${spaceId}/channels/${channelId}/posts`);
  }

  async createSpacePost(
    spaceId: number,
    channelId: number,
    payload: SpacePostCreatePayload,
  ): Promise<StorySpacePost> {
    return this.request<StorySpacePost>(`/story-spaces/${spaceId}/channels/${channelId}/posts`, {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  }

  async publishStory(spaceId: number, payload: PublishStoryPayload): Promise<PublishedStory> {
    return this.request<PublishedStory>(`/story-spaces/${spaceId}/publish`, {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  }

  async getPublishedStory(id: number): Promise<PublishedStory> {
    return this.request<PublishedStory>(`/published-stories/${id}`);
  }

  // Composition sessions — shared editor infrastructure (see lib/composition.ts)

  async createCompositionSession(payload: {
    surface: string;
    target_kind?: string;
    target_ref?: string;
    continues_session_id?: string;
  }): Promise<{ id: string; surface: string; status: string }> {
    return this.request(`/composition/sessions`, {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  }

  /** Read back a session the caller owns, including the counters the server
   *  holds for it. Used to resume a restored draft's session rather than
   *  starting its evidence over from zero. 404s for anyone else's session. */
  async getCompositionSession(
    sessionId: string,
  ): Promise<{ id: string; status: string; metrics?: Partial<CompositionMetrics> }> {
    return this.request(`/composition/sessions/${sessionId}`);
  }

  /** Reports integer counters only — never text. See lib/composition.ts. */
  async updateCompositionSession(
    sessionId: string,
    metrics: CompositionMetrics,
  ): Promise<{ id: string; status: string }> {
    return this.request(`/composition/sessions/${sessionId}`, {
      method: 'PATCH',
      body: JSON.stringify({ metrics }),
    });
  }

  // Notifications
  async getNotifications(limit = 30): Promise<Notification[]> {
    return this.request<Notification[]>(`/notifications?limit=${limit}`);
  }

  async getUnreadCount(): Promise<{ count: number }> {
    return this.request<{ count: number }>('/notifications/unread-count');
  }

  async markNotificationRead(id: number): Promise<void> {
    return this.request<void>(`/notifications/${id}/read`, { method: 'PATCH' });
  }

  async markAllNotificationsRead(): Promise<void> {
    return this.request<void>('/notifications/mark-all-read', { method: 'POST' });
  }

  // Style Shops
  async getStylePresets(shopType?: string): Promise<StylePreset[]> {
    const q = shopType ? `?shop_type=${shopType}` : '';
    return this.request<StylePreset[]>(`/style-shops/presets${q}`);
  }

  async getCharacterStyleElements(characterId: number): Promise<StyleElementsResponse> {
    return this.request<StyleElementsResponse>(`/characters/${characterId}/style-elements`);
  }

  async applyStyleElement(characterId: number, presetId: number, placement?: string): Promise<StyleElementsResponse> {
    return this.request<StyleElementsResponse>(`/characters/${characterId}/style-elements`, {
      method: 'POST',
      body: JSON.stringify({ preset_id: presetId, placement }),
    });
  }

  async archiveStyleElement(characterId: number, elementId: number): Promise<StyleElementsResponse> {
    return this.request<StyleElementsResponse>(`/characters/${characterId}/style-elements/${elementId}`, {
      method: 'DELETE',
    });
  }

  // Body Canon
  async getBodyMarkings(characterId: number): Promise<BodyCanonRead> {
    return this.request<BodyCanonRead>(`/characters/${characterId}/body-markings`);
  }

  async generateBodyAnchor(characterId: number, markingId: string): Promise<BodyAnchorResponse> {
    return this.request<BodyAnchorResponse>(
      `/characters/${characterId}/body-markings/${markingId}/generate-anchor`,
      { method: 'POST' },
    );
  }

  async lockBodyAnchor(characterId: number, markingId: string): Promise<BodyAnchorResponse> {
    return this.request<BodyAnchorResponse>(
      `/characters/${characterId}/body-markings/${markingId}/lock-anchor`,
      { method: 'POST' },
    );
  }

  async replaceBodyAnchor(characterId: number, markingId: string): Promise<BodyAnchorResponse> {
    return this.request<BodyAnchorResponse>(
      `/characters/${characterId}/body-markings/${markingId}/replace-anchor`,
      { method: 'POST' },
    );
  }

  // Body Identity Slots
  async getBodySlots(characterId: number): Promise<BodySlotsResponse> {
    return this.request<BodySlotsResponse>(`/characters/${characterId}/identity/body-slots`);
  }

  async generateBodySlot(characterId: number, slot: string): Promise<BodySlotsResponse> {
    return this.request<BodySlotsResponse>(
      `/characters/${characterId}/identity/body-slots/${slot}/generate`,
      { method: 'POST' },
    );
  }

  async lockBodySlot(characterId: number, slot: string): Promise<BodySlotsResponse> {
    return this.request<BodySlotsResponse>(
      `/characters/${characterId}/identity/body-slots/${slot}/lock`,
      { method: 'POST' },
    );
  }

  async replaceBodySlot(characterId: number, slot: string): Promise<BodySlotsResponse> {
    return this.request<BodySlotsResponse>(
      `/characters/${characterId}/identity/body-slots/${slot}/replace`,
      { method: 'POST' },
    );
  }

  async useExistingBodySlot(characterId: number, slot: string, imageId: number): Promise<BodySlotsResponse> {
    return this.request<BodySlotsResponse>(
      `/characters/${characterId}/identity/body-slots/${slot}/use-existing`,
      { method: 'POST', body: JSON.stringify({ image_id: imageId }) },
    );
  }

  async useExistingBodyAnchor(characterId: number, markingId: string, imageId: number): Promise<BodyAnchorResponse> {
    return this.request<BodyAnchorResponse>(
      `/characters/${characterId}/body-markings/${markingId}/use-existing-anchor`,
      { method: 'POST', body: JSON.stringify({ image_id: imageId }) },
    );
  }

  async adminCanonImport(
    characterId: number,
    targetSlot: 'body_front' | 'tattoo_layout',
    file: File,
    sourceNote?: string,
  ): Promise<CanonImportResponse> {
    const formData = new FormData();
    formData.append('file', file);
    formData.append('target_slot', targetSlot);
    if (sourceNote) formData.append('source_note', sourceNote);
    const token = this.getToken();
    const headers: Record<string, string> = {};
    if (token) headers['Authorization'] = `Bearer ${token}`;
    const resp = await fetch(`${API_BASE_URL}/characters/${characterId}/identity/canon-import`, {
      method: 'POST',
      headers,
      body: formData,
    });
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({ detail: resp.statusText }));
      throw new Error(typeof err.detail === 'string' ? err.detail : JSON.stringify(err.detail));
    }
    return resp.json();
  }

  // ── Editor Studio (Sprint E1) ─────────────────────────────────────────────

  /** Edit/transform 1-3 existing character images via POST /editor/generate. */
  async editorGenerate(form: FormData): Promise<import('../features/editorStudio/editorGenerate').EditorGenerateResult> {
    const token = this.getToken();
    const response = await fetch(`${API_BASE_URL}/editor/generate`, {
      method: 'POST',
      headers: token ? { Authorization: `Bearer ${token}` } : {},
      body: form,
      credentials: 'include',
    });
    if (!response.ok) {
      const error = await response
        .json()
        .catch(() => ({ detail: `Editor generation failed (HTTP ${response.status})` }));
      console.error('EDITOR_RESPONSE_ERROR', response.status, error);
      throw new Error(typeof error.detail === 'string' ? error.detail : JSON.stringify(error.detail));
    }
    const result = await response.json();
    console.log('EDITOR_RESPONSE', result);
    return result;
  }

  // ── Editor Studio async jobs (Sprint E5, self_hosted only) ────────────────

  /** Start an async self-hosted editor transform; returns the queued job. */
  async editorJobStart(form: FormData): Promise<import('../features/editorStudio/editorGenerate').EditorJob> {
    const token = this.getToken();
    const response = await fetch(`${API_BASE_URL}/editor/jobs`, {
      method: 'POST',
      headers: token ? { Authorization: `Bearer ${token}` } : {},
      body: form,
      credentials: 'include',
    });
    if (!response.ok) {
      const error = await response
        .json()
        .catch(() => ({ detail: `Editor job start failed (HTTP ${response.status})` }));
      console.error('EDITOR_JOB_ERROR', response.status, error);
      throw new Error(typeof error.detail === 'string' ? error.detail : JSON.stringify(error.detail));
    }
    const job = await response.json();
    console.log('EDITOR_JOB_STARTED', job);
    return job;
  }

  /** Poll one editor job by id (reconciles running jobs server-side). */
  async editorJobGet(jobId: number): Promise<import('../features/editorStudio/editorGenerate').EditorJob> {
    return this.request(`/editor/jobs/${jobId}`);
  }

  /** Latest editor job for a character, or null if none was ever started. */
  async editorJobLatest(characterId: number): Promise<import('../features/editorStudio/editorGenerate').EditorJob | null> {
    const envelope = await this.request<{ job: import('../features/editorStudio/editorGenerate').EditorJob | null }>(
      `/editor/jobs/latest?character_id=${characterId}`,
    );
    return envelope.job;
  }

  /** Cancel an active editor job (terminates its pod best-effort). */
  async editorJobCancel(jobId: number): Promise<import('../features/editorStudio/editorGenerate').EditorJob> {
    return this.request(`/editor/jobs/${jobId}/cancel`, { method: 'POST' });
  }

  // ── RP Story Threads ──────────────────────────────────────────────────────

  async createRPStory(data: CreateRPStoryRequest): Promise<RPStoryThreadDetail> {
    return this.request('/rp-stories', { method: 'POST', body: JSON.stringify(data) });
  }

  async listRPStories(): Promise<RPStoryThread[]> {
    return this.request('/rp-stories');
  }

  async getRPStory(threadId: number): Promise<RPStoryThreadDetail> {
    return this.request(`/rp-stories/${threadId}`);
  }

  async addPartnerTurn(threadId: number, data: AddPartnerTurnRequest): Promise<RPStoryTurn> {
    return this.request(`/rp-stories/${threadId}/partner-turn`, { method: 'POST', body: JSON.stringify(data) });
  }

  async generateThreadReply(threadId: number, data: GenerateThreadReplyRequest): Promise<GenerateThreadReplyResponse> {
    return this.request(`/rp-stories/${threadId}/generate-reply`, { method: 'POST', body: JSON.stringify(data) });
  }

  async saveGeneratedTurn(threadId: number, data: SaveGeneratedTurnRequest): Promise<RPStoryTurn> {
    return this.request(`/rp-stories/${threadId}/save-generated-turn`, { method: 'POST', body: JSON.stringify(data) });
  }

  async archiveRPStory(threadId: number): Promise<RPStoryThread> {
    return this.request(`/rp-stories/${threadId}/archive`, { method: 'PATCH' });
  }

  // ── Identity Canon (clean rebuild) ────────────────────────────────

  async getIdentityCanon(characterId: number): Promise<Record<string, unknown>> {
    return this.request(`/characters/${characterId}/identity-canon`);
  }

  async patchFaceCanon(characterId: number, data: Record<string, unknown>): Promise<Record<string, unknown>> {
    return this.request(`/characters/${characterId}/identity-canon/face`, {
      method: 'PATCH',
      body: JSON.stringify(data),
    });
  }

  async lockFaceCanon(characterId: number): Promise<Record<string, unknown>> {
    return this.request(`/characters/${characterId}/identity-canon/face/lock`, { method: 'POST' });
  }

  async patchBodyCanon(characterId: number, data: Record<string, unknown>): Promise<Record<string, unknown>> {
    return this.request(`/characters/${characterId}/identity-canon/body`, {
      method: 'PATCH',
      body: JSON.stringify(data),
    });
  }

  async lockBodyCanon(characterId: number): Promise<Record<string, unknown>> {
    return this.request(`/characters/${characterId}/identity-canon/body/lock`, { method: 'POST' });
  }

  async addCanonBodyMark(characterId: number, data: Record<string, unknown>): Promise<Record<string, unknown>> {
    return this.request(`/characters/${characterId}/identity-canon/body/marks`, {
      method: 'POST',
      body: JSON.stringify(data),
    });
  }

  async removeCanonBodyMark(characterId: number, markId: string): Promise<Record<string, unknown>> {
    return this.request(`/characters/${characterId}/identity-canon/body/marks/${markId}`, { method: 'DELETE' });
  }

  async addCanonAccessory(characterId: number, data: Record<string, unknown>): Promise<Record<string, unknown>> {
    return this.request(`/characters/${characterId}/identity-canon/accessories`, {
      method: 'POST',
      body: JSON.stringify(data),
    });
  }

  async removeCanonAccessory(characterId: number, accId: string): Promise<Record<string, unknown>> {
    return this.request(`/characters/${characterId}/identity-canon/accessories/${accId}`, { method: 'DELETE' });
  }

  async uploadCanonSlot(characterId: number, form: FormData): Promise<Record<string, unknown>> {
    const token = this.getToken();
    const response = await fetch(`${API_BASE_URL}/characters/${characterId}/identity-canon/upload`, {
      method: 'POST',
      headers: token ? { Authorization: `Bearer ${token}` } : {},
      body: form,
      credentials: 'include',
    });
    if (!response.ok) {
      const error = await response.json().catch(() => ({ detail: 'Upload failed' }));
      throw new Error(error.detail || `HTTP ${response.status}`);
    }
    return response.json();
  }

  // Upload the visual marking image for a specific permanent body mark.
  // The image — not prose — is the primary canon truth for the mark.
  async uploadCanonMarkImage(
    characterId: number,
    markId: string,
    form: FormData,
  ): Promise<Record<string, unknown>> {
    const token = this.getToken();
    const response = await fetch(
      `${API_BASE_URL}/characters/${characterId}/identity-canon/upload/mark/${markId}`,
      {
        method: 'POST',
        headers: token ? { Authorization: `Bearer ${token}` } : {},
        body: form,
        credentials: 'include',
      },
    );
    if (!response.ok) {
      const error = await response.json().catch(() => ({ detail: 'Upload failed' }));
      throw new Error(error.detail || `HTTP ${response.status}`);
    }
    return response.json();
  }

  async generateCanonScene(
    characterId: number,
    data: { prompt: string; include_accessories?: boolean },
  ): Promise<Record<string, unknown>> {
    return this.request(`/characters/${characterId}/identity-canon/scenes/generate`, {
      method: 'POST',
      body: JSON.stringify(data),
    });
  }

  // ── 18+ Studio (Adult Studio) — separate from Canon Studio ──────────

  async getAdultStudioStatus(characterId: number): Promise<AdultStudioStatus> {
    return this.request<AdultStudioStatus>(`/adult-studio/characters/${characterId}`);
  }

  async prepareAdultStudio(characterId: number): Promise<AdultStudioStatus> {
    return this.request<AdultStudioStatus>(
      `/adult-studio/characters/${characterId}/prepare`,
      { method: 'POST' },
    );
  }

  /**
   * Generate an adult-adjacent image. On failure the backend returns metadata
   * (provider, refs_count, failure_reason) — surfaced via the thrown error's
   * `.meta` so the UI can show why it failed (no silent fallback).
   */
  async generateAdultStudioImage(
    characterId: number,
    prompt: string,
  ): Promise<AdultStudioGenerateResult> {
    const token = this.getToken();
    const headers: Record<string, string> = { 'Content-Type': 'application/json' };
    if (token) headers['Authorization'] = `Bearer ${token}`;

    const response = await fetch(
      `${API_BASE_URL}/adult-studio/characters/${characterId}/generate`,
      { method: 'POST', headers, credentials: 'include', body: JSON.stringify({ prompt }) },
    );

    const payload = await response.json().catch(() => ({} as Record<string, unknown>));
    if (!response.ok) {
      const detail = (payload as { detail?: unknown }).detail;
      // detail may be a metadata object (generation failure) or a plain string (auth/safety).
      const meta = detail && typeof detail === 'object' ? (detail as AdultStudioGenerateResult) : undefined;
      const message =
        meta?.failure_reason ||
        (typeof detail === 'string' ? detail : `Generation failed (HTTP ${response.status})`);
      const err = new Error(message) as Error & { meta?: AdultStudioGenerateResult };
      if (meta) err.meta = meta;
      throw err;
    }
    return payload as AdultStudioGenerateResult;
  }

  /**
   * Founder Async Lite (Sprint 13). Launch ONE Summer-only generation job via the
   * VALIDATED RunPod masked-diffusion pipeline (active LoRA + enforcement plan + both
   * tattoo routes) — NOT the OpenAI gpt-image path. Returns the queued/running job
   * snapshot (HTTP 202). 409 if a founder job is already active.
   */
  async startFounderJob(characterId: number, prompt: string): Promise<AdultStudioFounderJob> {
    const token = this.getToken();
    const headers: Record<string, string> = { 'Content-Type': 'application/json' };
    if (token) headers['Authorization'] = `Bearer ${token}`;

    const response = await fetch(
      `${API_BASE_URL}/admin/adult-studio/characters/${characterId}/founder-generate`,
      { method: 'POST', headers, credentials: 'include', body: JSON.stringify({ prompt }) },
    );
    const payload = await response.json().catch(() => ({} as Record<string, unknown>));
    if (!response.ok) {
      const detail = (payload as { detail?: unknown }).detail;
      throw new Error(typeof detail === 'string' ? detail : `Launch failed (HTTP ${response.status})`);
    }
    return payload as AdultStudioFounderJob;
  }

  /** Poll the latest founder job (reconciles running→terminal). Null if none started. */
  async getFounderJob(characterId: number): Promise<AdultStudioFounderJob | null> {
    const token = this.getToken();
    const headers: Record<string, string> = {};
    if (token) headers['Authorization'] = `Bearer ${token}`;

    const response = await fetch(
      `${API_BASE_URL}/admin/adult-studio/characters/${characterId}/founder-job`,
      { method: 'GET', headers, credentials: 'include' },
    );
    const payload = await response.json().catch(() => ({} as Record<string, unknown>));
    if (!response.ok) {
      const detail = (payload as { detail?: unknown }).detail;
      throw new Error(typeof detail === 'string' ? detail : `Poll failed (HTTP ${response.status})`);
    }
    return ((payload as { job?: AdultStudioFounderJob | null }).job) ?? null;
  }

  /** Cancel the active founder job (terminate pod + mark failed). */
  async cancelFounderJob(characterId: number): Promise<AdultStudioFounderJob> {
    const token = this.getToken();
    const headers: Record<string, string> = {};
    if (token) headers['Authorization'] = `Bearer ${token}`;

    const response = await fetch(
      `${API_BASE_URL}/admin/adult-studio/characters/${characterId}/founder-job/cancel`,
      { method: 'POST', headers, credentials: 'include' },
    );
    const payload = await response.json().catch(() => ({} as Record<string, unknown>));
    if (!response.ok) {
      const detail = (payload as { detail?: unknown }).detail;
      throw new Error(typeof detail === 'string' ? detail : `Cancel failed (HTTP ${response.status})`);
    }
    return payload as AdultStudioFounderJob;
  }

  /**
   * Sprint E9 — experimental Replicate img2img test (admin only). Takes an existing
   * canon source image and runs PURE image-to-image through Replicate, then saves the
   * result to the image library. Additive fourth provider; does not affect the others.
   */
  async replicateTestAdultStudio(
    characterId: number,
    prompt?: string,
  ): Promise<ReplicateTestResult> {
    const token = this.getToken();
    const headers: Record<string, string> = { 'Content-Type': 'application/json' };
    if (token) headers['Authorization'] = `Bearer ${token}`;

    const response = await fetch(
      `${API_BASE_URL}/admin/adult-studio/characters/${characterId}/replicate-test`,
      { method: 'POST', headers, credentials: 'include', body: JSON.stringify(prompt ? { prompt } : {}) },
    );
    const payload = await response.json().catch(() => ({} as Record<string, unknown>));
    if (!response.ok) {
      const detail = (payload as { detail?: unknown }).detail;
      throw new Error(typeof detail === 'string' ? detail : `Replicate test failed (HTTP ${response.status})`);
    }
    return payload as ReplicateTestResult;
  }

  // ── Training Pack Review (S24W) — v4 LoRA candidates, Summer-only, admin ──────

  /** List staged v4 training-pack candidates + their review status. */
  async getTrainingCandidates(characterId: number): Promise<TrainingPackReview> {
    return this.request<TrainingPackReview>(
      `/admin/adult-studio/characters/${characterId}/training-candidates`,
    );
  }

  /** Approve / reject / reset one candidate; returns the updated entry. */
  async reviewTrainingCandidate(
    characterId: number,
    role: string,
    status: TrainingCandidateStatus,
  ): Promise<TrainingCandidate> {
    return this.request<TrainingCandidate>(
      `/admin/adult-studio/characters/${characterId}/training-candidates/${encodeURIComponent(role)}/review`,
      { method: 'POST', body: JSON.stringify({ status }) },
    );
  }

  /**
   * Fetch one candidate image as an object URL. The image endpoint is admin-gated
   * (bearer auth), so a plain <img src> can't load it — we blob-load with the token
   * and hand back an object URL the caller is responsible for revoking.
   */
  async getTrainingCandidateImageUrl(characterId: number, role: string): Promise<string> {
    const token = this.getToken();
    const headers: Record<string, string> = {};
    if (token) headers['Authorization'] = `Bearer ${token}`;
    const response = await fetch(
      `${API_BASE_URL}/admin/adult-studio/characters/${characterId}/training-candidates/${encodeURIComponent(role)}/image`,
      { method: 'GET', headers, credentials: 'include' },
    );
    if (!response.ok) throw new Error(`Failed to load candidate image (HTTP ${response.status})`);
    return URL.createObjectURL(await response.blob());
  }

  /**
   * Download the SDXL LoRA training pack ZIP for a Ready character. Triggers a
   * browser download; resolves once the download has been initiated.
   */
  async exportAdultStudioTrainingPack(characterId: number): Promise<void> {
    const token = this.getToken();
    const headers: Record<string, string> = {};
    if (token) headers['Authorization'] = `Bearer ${token}`;

    const response = await fetch(
      `${API_BASE_URL}/adult-studio/characters/${characterId}/training-pack`,
      { method: 'GET', headers, credentials: 'include' },
    );

    if (!response.ok) {
      const payload = await response.json().catch(() => ({} as Record<string, unknown>));
      const detail = (payload as { detail?: unknown }).detail;
      throw new Error(typeof detail === 'string' ? detail : `Export failed (HTTP ${response.status})`);
    }

    const blob = await response.blob();
    // Derive filename from Content-Disposition, fall back to a stable default.
    const disposition = response.headers.get('Content-Disposition') || '';
    const match = disposition.match(/filename="?([^"]+)"?/);
    const filename = match?.[1] || `ficshon_training_pack_${characterId}.zip`;

    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  }
}

export const apiClient = new ApiClient();
