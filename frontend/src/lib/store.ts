import { create } from 'zustand';
import type { User } from './types';
import { apiClient } from './apiClient';

/**
 * Where this browser stands with respect to authentication.
 *
 * The important state is `resolving`. A persisted token is only a claim: it is
 * not authentication until /me has accepted it. Before this existed the store
 * opened as "not authenticated", which is indistinguishable from "checked, and
 * they are a stranger" — so every protected route redirected a perfectly valid
 * session to /login during the first paint, and the deep link they arrived on
 * died there.
 *
 * This is the single source of auth truth. There is deliberately no companion
 * `isAuthenticated` boolean: two fields that must agree are two fields that
 * eventually will not.
 */
export type AuthStatus = 'resolving' | 'authenticated' | 'unauthenticated';

/**
 * The status to open with, decided synchronously at store creation.
 *
 * No token means there is nothing to resolve, so an anonymous visitor is
 * `unauthenticated` from the first render and redirects immediately with no
 * spinner. Only a token-bearing visitor waits.
 */
function initialStatus(): AuthStatus {
  return apiClient.hasToken() ? 'resolving' : 'unauthenticated';
}

interface AuthState {
  user: User | null;
  isLoading: boolean;
  status: AuthStatus;
  setUser: (user: User | null) => void;
  login: (email: string, password: string) => Promise<void>;
  register: (email: string, username: string, password: string, inviteCode: string) => Promise<void>;
  logout: () => void;
  fetchUser: () => Promise<void>;
  /** Resolve the persisted session once, at app start. */
  initializeAuth: () => void;
  /** Switch which owned character is this account's visible identity. */
  setActiveCharacter: (characterId: number | null) => Promise<void>;
}

export const useAuthStore = create<AuthState>((set, get) => ({
  user: null,
  isLoading: false,
  status: initialStatus(),

  setUser: (user) => set({ user, status: user ? 'authenticated' : 'unauthenticated' }),

  login: async (email, password) => {
    set({ isLoading: true });
    try {
      await apiClient.login(email, password);
      const user = await apiClient.getMe();
      set({ user, status: 'authenticated', isLoading: false });
    } catch (error) {
      set({ isLoading: false });
      throw error;
    }
  },

  register: async (email, username, password, inviteCode) => {
    set({ isLoading: true });
    try {
      await apiClient.register(email, username, password, inviteCode);
      await apiClient.login(email, password);
      const user = await apiClient.getMe();
      set({ user, status: 'authenticated', isLoading: false });
    } catch (error) {
      set({ isLoading: false });
      throw error;
    }
  },

  logout: () => {
    apiClient.logout();
    // Resolved, not resolving: the token is gone, so there is nothing left to
    // check and the next protected route must redirect at once rather than
    // hang on a spinner waiting for a /me that will never be issued.
    set({ user: null, status: 'unauthenticated' });
  },

  fetchUser: async () => {
    set({ isLoading: true });
    try {
      const user = await apiClient.getMe();
      set({ user, status: 'authenticated', isLoading: false });
    } catch (error) {
      set({ user: null, status: 'unauthenticated', isLoading: false });
    }
  },

  initializeAuth: () => {
    if (!apiClient.hasToken()) {
      set({ user: null, status: 'unauthenticated' });
      return;
    }
    set({ status: 'resolving' });
    void get().fetchUser();
  },

  setActiveCharacter: async (characterId) => {
    const user = await apiClient.setActiveCharacter(characterId);
    set({ user, status: 'authenticated' });
  },
}));
