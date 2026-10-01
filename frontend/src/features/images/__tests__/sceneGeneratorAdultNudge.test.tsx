// @vitest-environment jsdom
/**
 * W-02: the ordinary Scene Generator no longer interrupts generation to
 * advertise the 18+ Studio. The adult-adjacent nudge (Polish Phase 5.6, which
 * had narrowed it to admins) is gone for EVERY account — creator, seeder and
 * admin all generate directly, whatever the prompt, and the panel never links
 * to the Studio. The Studio itself is untouched and stays reachable by its
 * AdminRoute-guarded deep link (pinned in privilegedRoutes / routeBaseline).
 */
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { Character, User } from '@/lib/types';

const generateImage = vi.fn();
const submit = vi.fn();

vi.mock('@/features/characterCreation/shared/api', () => ({
  generateImage: (...a: unknown[]) => generateImage(...a),
}));
// Founder-only children reach the API on their own; none of that is under test.
vi.mock('@/features/images/components/ReferencePicker', () => ({ default: () => null }));
vi.mock('@/features/images/components/UploadImageButton', () => ({ default: () => null }));
vi.mock('@/features/images/useGenerationJob', () => ({
  useGenerationJob: () => ({
    phase: 'idle', job: null, image: null, error: '', busy: false,
    submit: (...a: unknown[]) => submit(...a), resume: vi.fn(), resumeJob: vi.fn(), reset: vi.fn(),
  }),
}));

import SceneGeneratorPanel from '@/features/images/components/SceneGeneratorPanel';
import { useAuthStore } from '@/lib/store';

const ORDINARY: User = {
  id: 7, email: 'me@test.invalid', username: 'me', character_count: 1,
  is_admin: false, is_seeder: false,
} as User;
const SEEDER: User = { ...ORDINARY, is_seeder: true } as User;
const ADMIN: User = { ...ORDINARY, is_admin: true } as User;

// visual_locked + has_identity_canon: past every readiness guard, so nothing
// but a nudge could stand between the button and a generation.
const CHARACTER = {
  id: 42, name: 'Taylor', species: 'human', visibility: 'public',
  visual_locked: true, has_identity_canon: true,
  created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z',
} as unknown as Character;

function renderPanel() {
  return render(
    <MemoryRouter initialEntries={['/images']}>
      <Routes>
        <Route
          path="/images"
          element={<SceneGeneratorPanel characters={[CHARACTER]} onGenerated={() => {}} />}
        />
        <Route path="/studio/18-plus" element={<p>STUDIO PAGE</p>} />
      </Routes>
    </MemoryRouter>,
  );
}

function typeAndGenerate(prompt: string) {
  fireEvent.change(screen.getByPlaceholderText(/Describe the image/), { target: { value: prompt } });
  fireEvent.click(screen.getByRole('button', { name: /Generate Image/ }));
}

beforeEach(() => {
  vi.clearAllMocks();
  generateImage.mockResolvedValue({ id: 1, url: '/x.png' });
  submit.mockResolvedValue(null);
});

afterEach(cleanup);

describe('SceneGeneratorPanel has no adult-adjacent 18+ Studio nudge (W-02)', () => {
  it('an ordinary creator generates an adult-adjacent prompt directly', async () => {
    useAuthStore.setState({ user: ORDINARY, status: 'authenticated' });
    renderPanel();
    typeAndGenerate('Taylor at the beach in a bikini');
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(screen.queryByText(/18\+ Studio/)).toBeNull();
    await waitFor(() => expect(generateImage).toHaveBeenCalledTimes(1));
    expect(generateImage.mock.calls[0][1]).toBe('Taylor at the beach in a bikini');
  });

  it.each([['seeder', SEEDER], ['admin', ADMIN]] as [string, User][])(
    'a %s generates an adult-adjacent prompt directly — no dialog, no Studio CTA',
    async (_who, user) => {
      useAuthStore.setState({ user, status: 'authenticated' });
      renderPanel();
      typeAndGenerate('Taylor in lingerie');
      expect(screen.queryByRole('dialog')).toBeNull();
      expect(screen.queryByText(/18\+ Studio/)).toBeNull();
      expect(screen.queryByRole('button', { name: 'Open 18+ Studio' })).toBeNull();
      expect(screen.queryByRole('button', { name: 'Continue here' })).toBeNull();
      // Founders submit through the async job pipeline (mocked here).
      await waitFor(() => expect(submit).toHaveBeenCalledTimes(1));
      expect(submit.mock.calls[0][1].prompt).toBe('Taylor in lingerie');
      expect(screen.queryByText('STUDIO PAGE')).toBeNull();
    },
  );
});
