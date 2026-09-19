// @vitest-environment jsdom
/**
 * The adult-adjacent nudge in SceneGeneratorPanel points at the 18+ Studio —
 * an admin-only destination (adult_studio.py mounts its router behind
 * require_admin). Polish Phase 5.6: an account that cannot open that door is
 * not shown the nudge; it simply generates. An admin keeps the nudge and its
 * "Open 18+ Studio" CTA. The gate is the canonical `isAdmin` entitlement, the
 * same one the Image Library's studio card uses — not a re-derived rule.
 */
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { Character, User } from '@/lib/types';

const generateImage = vi.fn();

vi.mock('@/features/characterCreation/shared/api', () => ({
  generateImage: (...a: unknown[]) => generateImage(...a),
}));
// Founder-only children and the async job hook reach the API on their own;
// none of that is under test here.
vi.mock('@/features/images/components/ReferencePicker', () => ({ default: () => null }));
vi.mock('@/features/images/components/UploadImageButton', () => ({ default: () => null }));
vi.mock('@/features/images/useGenerationJob', () => ({
  useGenerationJob: () => ({
    phase: 'idle', job: null, image: null, error: '', busy: false,
    submit: vi.fn(), resume: vi.fn(), resumeJob: vi.fn(), reset: vi.fn(),
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

// visual_locked + has_identity_canon: past every readiness guard, so the
// only thing between the button and a generation is the nudge.
const CHARACTER = {
  id: 42, name: 'Taylor', species: 'human', visibility: 'public',
  visual_locked: true, has_identity_canon: true,
  created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z',
} as unknown as Character;

function Studio() { return <p>STUDIO PAGE</p>; }

function renderPanel() {
  return render(
    <MemoryRouter initialEntries={['/images']}>
      <Routes>
        <Route
          path="/images"
          element={<SceneGeneratorPanel characters={[CHARACTER]} onGenerated={() => {}} />}
        />
        <Route path="/studio/18-plus" element={<Studio />} />
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
});

afterEach(cleanup);

describe('SceneGeneratorPanel adult-adjacent nudge', () => {
  it('an ordinary creator is not shown the nudge and generates directly', async () => {
    useAuthStore.setState({ user: ORDINARY, status: 'authenticated' });
    renderPanel();
    typeAndGenerate('Taylor at the beach in a bikini');
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(screen.queryByText(/18\+ Studio/)).toBeNull();
    await waitFor(() => expect(generateImage).toHaveBeenCalledTimes(1));
    expect(generateImage.mock.calls[0][1]).toBe('Taylor at the beach in a bikini');
  });

  it('a seeder is not shown the nudge either — the Studio router refuses non-admins', async () => {
    useAuthStore.setState({ user: SEEDER, status: 'authenticated' });
    renderPanel();
    typeAndGenerate('Taylor in lingerie');
    expect(screen.queryByRole('dialog')).toBeNull();
    // Founders generate through the job pipeline (mocked), not generateImage;
    // the point is that nothing interrupted the click.
    expect(screen.queryByText(/18\+ Studio/)).toBeNull();
  });

  it('an admin keeps the nudge and can open the 18+ Studio from it', async () => {
    useAuthStore.setState({ user: ADMIN, status: 'authenticated' });
    renderPanel();
    typeAndGenerate('Taylor at the beach in a bikini');
    const dialog = await screen.findByRole('dialog');
    expect(dialog.textContent).toMatch(/18\+ Studio/);
    fireEvent.click(screen.getByRole('button', { name: 'Open 18+ Studio' }));
    await screen.findByText('STUDIO PAGE');
  });

  it('an admin can still choose to continue here', async () => {
    useAuthStore.setState({ user: ADMIN, status: 'authenticated' });
    renderPanel();
    typeAndGenerate('Taylor poolside');
    await screen.findByRole('dialog');
    fireEvent.click(screen.getByRole('button', { name: 'Continue here' }));
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
  });

  it('a non-adult prompt never nudges anyone', async () => {
    useAuthStore.setState({ user: ADMIN, status: 'authenticated' });
    renderPanel();
    typeAndGenerate('Taylor reading in a library');
    expect(screen.queryByRole('dialog')).toBeNull();
  });
});
