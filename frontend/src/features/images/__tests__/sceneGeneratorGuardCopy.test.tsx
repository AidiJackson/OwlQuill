// @vitest-environment jsdom
/**
 * Readiness guard copy in SceneGeneratorPanel — Polish Phase 5.7.
 *
 * The guard CONDITIONS are computeGeneratorGuards' and are pinned in
 * generatorReadiness.test.ts; this pins that the panel still blocks and
 * allows exactly those states, and that what it says to an ordinary owner is
 * an action in product language — no "identity anchor", no "identity pack",
 * no "lock".
 */
import { cleanup, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { Character, User } from '@/lib/types';

vi.mock('@/features/characterCreation/shared/api', () => ({ generateImage: vi.fn() }));
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
  id: 7, email: 'me@test.invalid', username: 'me', character_count: 1, is_admin: false, is_seeder: false,
} as User;

const BASE = {
  id: 42, name: 'Taylor', species: 'human', visibility: 'public',
  created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z',
};

function renderWith(character: Record<string, unknown>) {
  return render(
    <MemoryRouter>
      <SceneGeneratorPanel characters={[{ ...BASE, ...character } as unknown as Character]} onGenerated={() => {}} />
    </MemoryRouter>,
  );
}

const generateButton = () => screen.getByRole('button', { name: /Generate Image/ }) as HTMLButtonElement;
const IMPLEMENTATION_TERMS = /identity anchor|anchor JSON|identity pack|lock your|regenerate and accept/i;

beforeEach(() => {
  useAuthStore.setState({ user: ORDINARY, status: 'authenticated' });
});
afterEach(cleanup);

describe('SceneGeneratorPanel guard copy', () => {
  it('not established, canon generated (abandoned pack): blocked, sent to establish it on the character page', () => {
    renderWith({ visual_locked: false, has_identity_canon: true });
    const note = screen.getByRole('status');
    expect(note.textContent).toMatch(/Taylor's Character Canon isn't established yet/);
    expect(note.textContent).toMatch(/Open their page and establish their Character Canon/);
    expect(note.textContent).not.toMatch(IMPLEMENTATION_TERMS);
    expect(generateButton().disabled).toBe(true);
  });

  it('not established, no canon (true draft): blocked, told to finish setup from the Characters page', () => {
    renderWith({ visual_locked: false, has_identity_canon: false });
    const note = screen.getByRole('status');
    expect(note.textContent).toMatch(/Finish their setup from the Characters page/);
    expect(note.textContent).not.toMatch(IMPLEMENTATION_TERMS);
    expect(generateButton().disabled).toBe(true);
  });

  it('established legacy character with no canon and no reference record: blocked, told where to look', () => {
    renderWith({ visual_locked: true, has_identity_canon: false, identity_anchor_json: '{"anchors":{}}' });
    const note = screen.getByRole('status');
    expect(note.textContent).toMatch(/can't find Taylor's reference images/);
    expect(note.textContent).toMatch(/check their Character Canon/);
    expect(note.textContent).not.toMatch(IMPLEMENTATION_TERMS);
    expect(generateButton().disabled).toBe(true);
  });

  it('established with a canon: no guard, generation offered (button gated on the prompt only)', () => {
    renderWith({ visual_locked: true, has_identity_canon: true });
    expect(screen.queryByRole('status')).toBeNull();
    expect(generateButton().disabled).toBe(true); // empty prompt
  });

  it('established legacy character with a reference record: no guard', () => {
    renderWith({ visual_locked: true, has_identity_canon: false, identity_anchor_json: '{"anchors":{"front":{"url":"/a.png"}}}' });
    expect(screen.queryByRole('status')).toBeNull();
  });
});
