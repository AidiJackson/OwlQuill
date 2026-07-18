import { create } from 'zustand';
import type { User } from './types';
import { apiClient } from './apiClient';

interface AuthState {
  user: User | null;
  isLoading: boolean;
  isAuthenticated: boolean;
  setUser: (user: User | null) => void;
  login: (email: string, password: string) => Promise<void>;
  register: (email: string, username: string, password: string, inviteCode: string) => Promise<void>;
  logout: () => void;
  fetchUser: () => Promise<void>;
  /** Switch which owned character is this account's visible identity. */
  setActiveCharacter: (characterId: number | null) => Promise<void>;
}

export const useAuthStore = create<AuthState>((set) => ({
  user: null,
  isLoading: false,
  isAuthenticated: false,

  setUser: (user) => set({ user, isAuthenticated: !!user }),

  login: async (email, password) => {
    set({ isLoading: true });
    try {
      await apiClient.login(email, password);
      const user = await apiClient.getMe();
      set({ user, isAuthenticated: true, isLoading: false });
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
      set({ user, isAuthenticated: true, isLoading: false });
    } catch (error) {
      set({ isLoading: false });
      throw error;
    }
  },

  logout: () => {
    apiClient.logout();
    set({ user: null, isAuthenticated: false });
  },

  fetchUser: async () => {
    set({ isLoading: true });
    try {
      const user = await apiClient.getMe();
      set({ user, isAuthenticated: true, isLoading: false });
    } catch (error) {
      set({ user: null, isAuthenticated: false, isLoading: false });
    }
  },

  setActiveCharacter: async (characterId) => {
    const user = await apiClient.setActiveCharacter(characterId);
    set({ user, isAuthenticated: true });
  },
}));
