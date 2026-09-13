// @vitest-environment jsdom
//
// CharacterCreationFlow — resume and persistence (Polish Phase 1, C2 / C8).
//
// The flow talks to two API surfaces: apiClient (character rows) and the
// creation feature's shared/api (DNA, sketch, pack). Both are mocked at the
// module boundary; nothing here touches fetch.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

const api = vi.hoisted(() => ({
  getCharacter: vi.fn(),
  createCharacter: vi.fn(),
  updateCharacter: vi.fn(),
}));
const creationApi = vi.hoisted(() => ({
  getDNA: vi.fn(),
  upsertDNA: vi.fn(),
}));

vi.mock('@/lib/apiClient', () => ({ apiClient: api }));
vi.mock('../shared/api', async (importOriginal) => {
  const original = await importOriginal<typeof import('../shared/api')>();
  return { ...original, getDNA: creationApi.getDNA, upsertDNA: creationApi.upsertDNA };
});

import CharacterCreationFlow from '../CharacterCreationFlow';

afterEach(cleanup);
beforeEach(() => {
  api.getCharacter.mockReset();
  api.createCharacter.mockReset();
  api.updateCharacter.mockReset();
  creationApi.getDNA.mockReset();
  creationApi.upsertDNA.mockReset();
});

const COMPLETE_SPEC = {
  style: '',
  gender: 'female',
  age_band: '26-35',
  species: 'vampire',
  species_tells: ['subtle_fangs'],
  identity: { hair_color: 'Auburn', hair_length: 'Long', eye_color: 'Green', skin_tone: 'Fair', face_features: [] },
  build: { body_type: '', height_band: '' },
  marks_accessories: { items: [] },
  wardrobe: { outfit_type: '', primary_color: '', secondary_color: '', footwear: '', accessory: '', notes: '' },
  extra_notes: '',
  face_shape: 'angular',
};

function renderFlow(path = '/characters/new') {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <CharacterCreationFlow />
    </MemoryRouter>,
  );
}

const pressed = (group: string) =>
  within(screen.getByRole('group', { name: group }))
    .getAllByRole('button')
    .filter((b) => b.getAttribute('aria-pressed') === 'true')
    .map((b) => b.textContent);

describe('resume (C2)', () => {
  it('opens at the Sketch when a complete Interview was stored, and Back shows the stored answers', async () => {
    api.getCharacter.mockResolvedValue({ id: 7, name: 'Tatiana', alias: 'The Countess' });
    creationApi.getDNA.mockResolvedValue({
      visual_traits_json: { personality_traits: ['Cunning'], identity_spec: COMPLETE_SPEC },
    });
    renderFlow('/characters/new?characterId=7');

    await waitFor(() => expect(screen.getByRole('heading', { name: 'Sketch' })).toBeTruthy());
    expect(screen.getByText('Step 2: Sketch')).toBeTruthy();

    fireEvent.click(screen.getByRole('button', { name: 'Back' }));
    expect(screen.getByRole('heading', { name: 'Interview' })).toBeTruthy();
    expect((screen.getByLabelText('Character name') as HTMLInputElement).value).toBe('Tatiana');
    expect((screen.getByLabelText('Character alias') as HTMLInputElement).value).toBe('The Countess');
    expect(pressed('Gender')).toEqual(['Woman']);
    expect(pressed('Age range')).toEqual(['26-35']);
    expect(pressed('Species')).toEqual(['Vampire']);
  });

  it('opens at the Interview, name filled, when no DNA was stored', async () => {
    api.getCharacter.mockResolvedValue({ id: 8, name: 'Bertie', alias: null });
    creationApi.getDNA.mockResolvedValue(null);
    renderFlow('/characters/new?characterId=8');

    await waitFor(() => expect(screen.getByRole('heading', { name: 'Interview' })).toBeTruthy());
    expect((screen.getByLabelText('Character name') as HTMLInputElement).value).toBe('Bertie');
    expect(pressed('Gender')).toEqual([]);
  });

  it('opens at the Interview with partial answers restored when the stored Interview is incomplete', async () => {
    api.getCharacter.mockResolvedValue({ id: 9, name: 'Elly', alias: '' });
    creationApi.getDNA.mockResolvedValue({
      visual_traits_json: { identity_spec: { ...COMPLETE_SPEC, age_band: '' } },
    });
    renderFlow('/characters/new?characterId=9');

    await waitFor(() => expect(screen.getByRole('heading', { name: 'Interview' })).toBeTruthy());
    expect(screen.queryByRole('heading', { name: 'Sketch' })).toBeNull();
    expect(pressed('Gender')).toEqual(['Woman']);
    expect(pressed('Age range')).toEqual([]);
  });

  it('reports a load failure rather than silently starting a new character', async () => {
    api.getCharacter.mockRejectedValue(new Error('nope'));
    creationApi.getDNA.mockResolvedValue(null);
    renderFlow('/characters/new?characterId=10');
    await waitFor(() => expect(screen.getByText('Failed to load draft character.')).toBeTruthy());
  });
});

describe('Interview → persistence (C8, C4, C17)', () => {
  it('writes the Character row and the DNA from the same Interview answers', async () => {
    api.createCharacter.mockResolvedValue({ id: 42, name: 'Bertie' });
    creationApi.upsertDNA.mockResolvedValue({});
    renderFlow();

    fireEvent.change(screen.getByLabelText('Character name'), { target: { value: '  Bertie ' } });
    fireEvent.change(screen.getByLabelText('Character alias'), { target: { value: 'Bert' } });
    fireEvent.click(within(screen.getByRole('group', { name: 'Gender' })).getByRole('button', { name: 'Man' }));
    fireEvent.click(within(screen.getByRole('group', { name: 'Age range' })).getByRole('button', { name: '36-50' }));
    fireEvent.click(within(screen.getByRole('group', { name: 'Species' })).getByRole('button', { name: 'Werewolf' }));
    fireEvent.click(screen.getByRole('button', { name: 'Continue to Sketch' }));

    await waitFor(() => expect(creationApi.upsertDNA).toHaveBeenCalledTimes(1));

    expect(api.createCharacter).toHaveBeenCalledWith({
      name: 'Bertie',
      alias: 'Bert',
      species: 'Werewolf',
      age: '36-50',
    });

    const [cid, dna] = creationApi.upsertDNA.mock.calls[0];
    expect(cid).toBe(42);
    expect(dna.species).toBe('werewolf');
    expect(dna.gender_presentation).toBe('male');
    expect(dna.structural_profile_json).toEqual({ age_band: '36-50' });
    expect(dna.visual_traits_json.identity_spec.gender).toBe('male');
    expect(dna.visual_traits_json.identity_spec.age_band).toBe('36-50');
    // Dead state and removed controls do not enter the payload.
    expect('vibe' in dna.visual_traits_json).toBe(false);
    expect(dna.visual_traits_json.identity_spec.brow_type).toBeUndefined();
    expect(dna.visual_traits_json.identity_spec.marks_accessories.items).toEqual([]);
    expect(dna.visual_traits_json.identity_spec.extra_notes).toBe('');

    await waitFor(() => expect(screen.getByRole('heading', { name: 'Sketch' })).toBeTruthy());
  });

  it('updates rather than recreates a resumed character', async () => {
    api.getCharacter.mockResolvedValue({ id: 7, name: 'Tatiana', alias: '' });
    creationApi.getDNA.mockResolvedValue({ visual_traits_json: { identity_spec: COMPLETE_SPEC } });
    api.updateCharacter.mockResolvedValue({ id: 7 });
    creationApi.upsertDNA.mockResolvedValue({});
    renderFlow('/characters/new?characterId=7');
    await waitFor(() => expect(screen.getByRole('heading', { name: 'Sketch' })).toBeTruthy());

    fireEvent.click(screen.getByRole('button', { name: 'Back' }));
    fireEvent.click(screen.getByRole('button', { name: 'Continue to Sketch' }));

    await waitFor(() => expect(creationApi.upsertDNA).toHaveBeenCalledTimes(1));
    expect(api.createCharacter).not.toHaveBeenCalled();
    expect(api.updateCharacter).toHaveBeenCalledWith(7, expect.objectContaining({ name: 'Tatiana', species: 'Vampire', age: '26-35' }));
  });
});
