// @vitest-environment jsdom
//
// Phase 5.2 (PD-3): the Scene Images surface inside CanonManager is founder-
// only. These pin the gate from every direction an ordinary owner could reach
// it — the tab list, stale tab state, and the render site — plus the two
// founder-facing truths: the surface is still there for founders, and its
// lock copy describes what the server does (no lock is required to generate).
//
// This is UI gating only. The cost control is server-side
// (``check_weekly_quota`` on the scene endpoint) and is proven in
// backend/tests/test_phase5_2_canon_scene_quota.py.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';

const getIdentityCanon = vi.fn();
const generateCanonScene = vi.fn();

vi.mock('@/lib/apiClient', () => ({
  apiClient: new Proxy(
    {},
    {
      get: (_t, prop) => {
        if (prop === 'getIdentityCanon') return getIdentityCanon;
        if (prop === 'generateCanonScene') return generateCanonScene;
        if (prop === 'hasToken') return () => true;
        return () => Promise.resolve({});
      },
    },
  ),
}));

import CanonManager from '@/components/CanonManager';

function makeCanon(overrides: Record<string, unknown> = {}) {
  return {
    id: 1,
    character_id: 7,
    status: 'draft',
    face_canon: {
      face_front_image_url: null,
      face_left_3q_image_url: null,
      face_right_3q_image_url: null,
      face_profile_image_url: null,
      face_expression_image_url: null,
      face_description: null,
      locked: false,
    },
    body_canon: {
      body_front_image_url: null,
      body_left_image_url: null,
      body_right_image_url: null,
      body_back_image_url: null,
      body_map_image_url: null,
      final_character_card_image_url: null,
      torso_front_image_url: null,
      torso_side_image_url: null,
      standing_relaxed_image_url: null,
      seated_relaxed_image_url: null,
      height: null,
      build: null,
      skin_tone: null,
      body_description: null,
      permanent_body_marks: [],
      locked: false,
    },
    accessories: [],
    face_locked: false,
    body_locked: false,
    updated_at: '2026-09-19T00:00:00Z',
    locked_at: null,
    ...overrides,
  };
}

const OLD_MISLEADING_COPY = /Lock at least Face Canon or Body Canon before generating scenes/;
const TRUTHFUL_COPY = /Scenes will still generate/;
const FOUNDER_ONLY_CONTROLS = ['Generate Scene', 'Lock Face Canon', 'Lock Body Canon', 'Upload', 'Replace'];

function renderManager(props: { isFounder: boolean; isOwner?: boolean }) {
  return render(<CanonManager characterId={7} isOwner={props.isOwner ?? true} isFounder={props.isFounder} />);
}

// Phase 5.7: the status line is role-aware — founders read the lock flags,
// owners read one product word — and tabs carry tab semantics.
async function waitForCanon(isFounder: boolean) {
  await waitFor(() =>
    expect(screen.getAllByText(isFounder ? /Canon: draft/ : /In progress/).length).toBeGreaterThan(0),
  );
}

function tabButton(label: string) {
  return screen.queryByRole('tab', { name: label });
}

beforeEach(() => {
  getIdentityCanon.mockReset();
  generateCanonScene.mockReset();
  getIdentityCanon.mockResolvedValue(makeCanon());
});
afterEach(cleanup);

describe('CanonManager — Scene Images gating (Phase 5.2, PD-3)', () => {
  it('ordinary owner does not see the Scene Images tab or surface', async () => {
    renderManager({ isFounder: false });
    await waitForCanon(false);

    expect(tabButton('Scene Images')).toBeNull();
    expect(screen.queryByText('Generate Scene')).toBeNull();
    expect(screen.queryByPlaceholderText(/standing on a beach/)).toBeNull();
    // The owner tabs are all still there.
    expect(tabButton('Face')).toBeTruthy();
    expect(tabButton('Body')).toBeTruthy();
    expect(tabButton('Accessories')).toBeTruthy();
  });

  it('a stale "scenes" selection falls back to Face Canon when founder access is lost', async () => {
    // Start as a founder, select Scene Images, then re-render as an ordinary
    // owner with the same component instance — the tab state still says
    // "scenes", and the view must not honour it.
    const view = renderManager({ isFounder: true });
    await waitForCanon(true);
    fireEvent.click(screen.getByRole('tab', { name: 'Scene Images' }));
    expect(screen.getByText('Generate Scene')).toBeTruthy();

    view.rerender(<CanonManager characterId={7} isOwner isFounder={false} />);

    expect(tabButton('Scene Images')).toBeNull();
    expect(screen.queryByText('Generate Scene')).toBeNull();
    expect(screen.queryByPlaceholderText(/standing on a beach/)).toBeNull();
    // Fell back to a valid owner-visible section, not an empty pane.
    expect(screen.getByRole('heading', { name: 'Face' })).toBeTruthy();
    expect(generateCanonScene).not.toHaveBeenCalled();
  });

  it('no founder-only control leaks into the owner view on any tab', async () => {
    renderManager({ isFounder: false });
    await waitForCanon(false);

    for (const label of ['Face', 'Body', 'Accessories']) {
      fireEvent.click(screen.getByRole('tab', { name: label }));
      for (const control of FOUNDER_ONLY_CONTROLS) {
        expect(screen.queryByText(control), `${control} leaked on ${label}`).toBeNull();
      }
    }
  });

  it('founder retains the Scene Images tab and can generate', async () => {
    generateCanonScene.mockResolvedValue({ id: 99, url: '/static/scene.png' });
    renderManager({ isFounder: true });
    await waitForCanon(true);

    fireEvent.click(screen.getByRole('tab', { name: 'Scene Images' }));
    const button = screen.getByText('Generate Scene').closest('button') as HTMLButtonElement;
    expect(button.disabled).toBe(true); // empty prompt only

    fireEvent.change(screen.getByPlaceholderText(/standing on a beach/), {
      target: { value: 'on a rooftop at dusk' },
    });
    expect(button.disabled).toBe(false);
    fireEvent.click(button);
    await waitFor(() => expect(generateCanonScene).toHaveBeenCalledWith(7, { prompt: 'on a rooftop at dusk' }));
  });

  it('founder lock copy is truthful: nothing locked does not block generation', async () => {
    renderManager({ isFounder: true });
    await waitForCanon(true);
    fireEvent.click(screen.getByRole('tab', { name: 'Scene Images' }));

    // The old copy claimed a rule the server never had.
    expect(screen.queryByText(OLD_MISLEADING_COPY)).toBeNull();
    // The new copy says what actually happens.
    expect(screen.getByText(TRUTHFUL_COPY)).toBeTruthy();
    // And the button agrees with it: unlocked canon does not disable generation.
    fireEvent.change(screen.getByPlaceholderText(/standing on a beach/), { target: { value: 'x' } });
    const button = screen.getByText('Generate Scene').closest('button') as HTMLButtonElement;
    expect(button.disabled).toBe(false);
  });

  it('founder draft-canon note disappears once either section is locked', async () => {
    getIdentityCanon.mockResolvedValue(makeCanon({ face_locked: true }));
    renderManager({ isFounder: true });
    await waitFor(() => expect(screen.getByText(/Face: locked/)).toBeTruthy());
    fireEvent.click(screen.getByRole('tab', { name: 'Scene Images' }));

    expect(screen.queryByText(TRUTHFUL_COPY)).toBeNull();
    expect(screen.queryByText(OLD_MISLEADING_COPY)).toBeNull();
  });
});
