import type { User, Character, CharacterSearchResult, Realm, Post, Comment, Reaction, Token, Scene, ScenePost, PublicUserProfile, ProfileTimelineItem } from './types';

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
    });

    if (!response.ok) {
      const error = await response.json().catch(() => ({ detail: 'An error occurred' }));
      throw new Error(error.detail || `HTTP ${response.status}`);
    }

    if (response.status === 204) {
      return null as T;
    }

    return response.json();
  }

  // Auth
  async register(email: string, username: string, password: string): Promise<User> {
    return this.request<User>('/auth/register', {
      method: 'POST',
      body: JSON.stringify({ email, username, password }),
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

  // Users
  async updateMe(data: { display_name?: string; bio?: string; avatar_url?: string }): Promise<User> {
    return this.request<User>('/users/me', {
      method: 'PATCH',
      body: JSON.stringify(data),
    });
  }

  async getUserProfile(username: string): Promise<PublicUserProfile> {
    return this.request<PublicUserProfile>(`/users/${encodeURIComponent(username)}`);
  }

  async getUserTimeline(username: string, limit = 20): Promise<ProfileTimelineItem[]> {
    return this.request<ProfileTimelineItem[]>(`/users/${encodeURIComponent(username)}/timeline?limit=${limit}`);
  }

  // Characters
  async getCharacters(): Promise<Character[]> {
    return this.request<Character[]>('/characters/');
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

  async createPost(realmId: number, data: Partial<Post>): Promise<Post> {
    return this.request<Post>(`/posts/realms/${realmId}/posts`, {
      method: 'POST',
      body: JSON.stringify(data),
    });
  }

  async getPost(id: number): Promise<Post> {
    return this.request<Post>(`/posts/${id}`);
  }

  // Comments
  async getPostComments(postId: number): Promise<Comment[]> {
    return this.request<Comment[]>(`/comments/posts/${postId}/comments`);
  }

  async createComment(postId: number, data: Partial<Comment>): Promise<Comment> {
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

  async createScenePost(sceneId: number, data: { content: string; character_id?: number; reply_to_id?: number }): Promise<ScenePost> {
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
}

export const apiClient = new ApiClient();
