// @vitest-environment jsdom
/**
 * W-02: the ordinary generator is product-facing, not provider-facing.
 *
 *   ordinary creator  no provider selector at all — and still sends
 *                     provider_option "option2" (Google / Canon) explicitly
 *   seeder            Canon · Recommended (option2, default) + OpenAI (option1)
 *   admin             Canon · Recommended (option2, default) + OpenAI · Admin
 *                     (option1); Grok is no longer offered here
 *
 * Only the UI changed: the request payload for each role is pinned below so a
 * future edit cannot silently change what the server is asked for. Every
 * network-facing function is mocked — no provider is ever called.
 */
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { Character, User } from '@/lib/types';

const generateImage = vi.fn();
const submit = vi.fn();

vi.mock('@/features/characterCreation/shared/api', () => ({
  generateImage: (...a: unknown[]) => generateImage(...a),
}));
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

const CHARACTER = {
  id: 42, name: 'Taylor', species: 'human', visibility: 'public',
  visual_locked: true, has_identity_canon: true,
  created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z',
} as unknown as Character;

function renderPanel(user: User) {
  useAuthStore.setState({ user, status: 'authenticated' });
  return render(
    <MemoryRouter>
      <SceneGeneratorPanel characters={[CHARACTER]} onGenerated={() => {}} />
    </MemoryRouter>,
  );
}

function typeAndGenerate(prompt: string) {
  fireEvent.change(screen.getByPlaceholderText(/Describe the image/), { target: { value: prompt } });
  fireEvent.click(screen.getByRole('button', { name: /Generate Image/ }));
}

const button = (name: RegExp) => screen.queryByRole('button', { name });

beforeEach(() => {
  vi.clearAllMocks();
  generateImage.mockResolvedValue({ id: 1, url: '/x.png' });
  submit.mockResolvedValue(null);
});
afterEach(cleanup);

describe('ordinary creator', () => {
  it('sees no provider selector of any kind', () => {
    renderPanel(ORDINARY);
    expect(button(/Canon/)).toBeNull();
    expect(button(/Recommended/)).toBeNull();
    expect(button(/OpenAI/)).toBeNull();
    expect(button(/Grok/)).toBeNull();
    expect(screen.queryByTitle(/Google/)).toBeNull();
    // The product controls are all still there.
    expect(screen.getByRole('combobox')).toBeTruthy();
    expect(button(/Generate Image/)).toBeTruthy();
  });

  it('still submits option2 explicitly, with the character and no references — payload unchanged', async () => {
    renderPanel(ORDINARY);
    typeAndGenerate('Taylor reading in a library');
    await waitFor(() => expect(generateImage).toHaveBeenCalledTimes(1));
    // generateImage(characterId, prompt, include_character, provider_option, is_cover)
    expect(generateImage.mock.calls[0]).toEqual([42, 'Taylor reading in a library', true, 'option2', false]);
    expect(submit).not.toHaveBeenCalled();
  });

  it('"No character" still routes through the first character with include_character=false and option2', async () => {
    renderPanel(ORDINARY);
    fireEvent.change(screen.getByRole('combobox'), { target: { value: 'none' } });
    typeAndGenerate('A misty harbour at dawn');
    await waitFor(() => expect(generateImage).toHaveBeenCalledTimes(1));
    expect(generateImage.mock.calls[0]).toEqual([42, 'A misty harbour at dawn', false, 'option2', false]);
  });
});

describe('Seeder', () => {
  it('sees Canon and OpenAI, not Grok', () => {
    renderPanel(SEEDER);
    expect(button(/Canon · Recommended/)).toBeTruthy();
    expect(button(/^OpenAI$/)).toBeTruthy();
    expect(button(/Grok/)).toBeNull();
  });

  it('defaults to option2 and submits it with the unchanged job payload', async () => {
    renderPanel(SEEDER);
    typeAndGenerate('Taylor at a market');
    await waitFor(() => expect(submit).toHaveBeenCalledTimes(1));
    expect(submit.mock.calls[0]).toEqual([42, {
      prompt: 'Taylor at a market',
      include_character: true,
      provider_option: 'option2',
      is_cover: false,
      reference_image_ids: [],
      reference_roles: [],
    }]);
    expect(generateImage).not.toHaveBeenCalled();
  });

  it('can select OpenAI, and the submission carries option1', async () => {
    renderPanel(SEEDER);
    fireEvent.click(button(/^OpenAI$/)!);
    typeAndGenerate('Taylor at a market');
    await waitFor(() => expect(submit).toHaveBeenCalledTimes(1));
    expect(submit.mock.calls[0][1].provider_option).toBe('option1');
  });
});

describe('Admin', () => {
  it('sees Canon and OpenAI · Admin, and no Grok', () => {
    renderPanel(ADMIN);
    expect(button(/Canon · Recommended/)).toBeTruthy();
    expect(button(/OpenAI · Admin/)).toBeTruthy();
    expect(button(/Grok/)).toBeNull();
    expect(screen.queryByTitle(/Grok/)).toBeNull();
  });

  it('defaults to option2 and can switch to option1', async () => {
    renderPanel(ADMIN);
    typeAndGenerate('Taylor at a market');
    await waitFor(() => expect(submit).toHaveBeenCalledTimes(1));
    expect(submit.mock.calls[0][1].provider_option).toBe('option2');

    fireEvent.click(button(/OpenAI · Admin/)!);
    typeAndGenerate('Taylor at a market again');
    await waitFor(() => expect(submit).toHaveBeenCalledTimes(2));
    expect(submit.mock.calls[1][1].provider_option).toBe('option1');
  });
});
