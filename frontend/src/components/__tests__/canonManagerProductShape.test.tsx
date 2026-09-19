// @vitest-environment jsdom
/**
 * CanonManager product shape — Polish Phase 5.7.
 *
 * Two audiences share one component. The ordinary owner sees Face / Body /
 * Accessories, one status word ("Established" / "In progress") with what it
 * means, the reference imagery that exists, their notes, marks and
 * accessories — and no empty founder upload slots, no lock controls, no
 * technical lock flags. The founder additionally sees every slot with
 * upload/replace, the lock buttons, the lock-flag status bar and Scene
 * Images. Status wording is pinned to what the backend does: locking sets
 * flags and enables generation; it freezes nothing. Stale state — a stale
 * tab, a character switch, a slow response — can never show the wrong
 * character's canon or a hidden panel.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';

const getIdentityCanon = vi.fn();
const patchFaceCanon = vi.fn();
const removeCanonBodyMark = vi.fn();
const addCanonBodyMark = vi.fn();
const addCanonAccessory = vi.fn();
const removeCanonAccessory = vi.fn();
const lockFaceCanon = vi.fn();
const lockBodyCanon = vi.fn();
const patchBodyCanon = vi.fn();

vi.mock('@/lib/apiClient', () => ({
  apiClient: new Proxy(
    {},
    {
      get: (_t, prop) => {
        const table: Record<string, unknown> = {
          getIdentityCanon, patchFaceCanon, removeCanonBodyMark, addCanonBodyMark,
          addCanonAccessory, removeCanonAccessory, lockFaceCanon, lockBodyCanon, patchBodyCanon,
          hasToken: () => true,
        };
        return table[prop as string] ?? (() => Promise.resolve({}));
      },
    },
  ),
}));

import CanonManager from '@/components/CanonManager';
import canonManagerSource from '../CanonManager.tsx?raw';
import sceneGeneratorSource from '../../features/images/components/SceneGeneratorPanel.tsx?raw';
import characterDetailSource from '../../pages/CharacterDetail.tsx?raw';

const MARK = {
  id: 'm1', label: 'Left sleeve', type: 'tattoo', body_region: 'left_full_arm', side: 'left',
  description: 'black script', reference_image_url: null, detail_crop_url: null, locked: false,
};
const ACCESSORY = {
  id: 'a1', label: 'Venetian mask', type: 'mask', description: 'gold filigree half-mask',
  trigger_keywords: ['mask', 'masked'], design_anchor_image_url: null, fit_anchor_image_url: null, locked: false,
};

function makeCanon(overrides: Record<string, unknown> = {}, face: Record<string, unknown> = {}, body: Record<string, unknown> = {}) {
  return {
    id: 1, character_id: 7, status: 'draft',
    face_canon: {
      face_front_image_url: null, face_left_3q_image_url: null, face_right_3q_image_url: null,
      face_profile_image_url: null, face_expression_image_url: null, face_description: null, locked: false,
      ...face,
    },
    body_canon: {
      body_front_image_url: null, body_left_image_url: null, body_right_image_url: null,
      body_back_image_url: null, body_map_image_url: null, final_character_card_image_url: null,
      torso_front_image_url: null, torso_side_image_url: null, standing_relaxed_image_url: null,
      seated_relaxed_image_url: null, height: null, build: null, skin_tone: null,
      body_description: null, permanent_body_marks: [], locked: false,
      ...body,
    },
    accessories: [],
    face_locked: false, body_locked: false,
    updated_at: '2026-09-19T00:00:00Z', locked_at: null,
    ...overrides,
  };
}

/** A finished ordinary-owner character: both sections locked, images present. */
function establishedCanon(extra: Record<string, unknown> = {}) {
  return makeCanon(
    { status: 'locked', face_locked: true, body_locked: true, locked_at: '2026-09-19T00:00:00Z', ...extra },
    { face_front_image_url: '/f.png', face_left_3q_image_url: '/l.png', face_description: 'sharp jaw', locked: true },
    { body_front_image_url: '/b.png', standing_relaxed_image_url: '/s.png', permanent_body_marks: [MARK], locked: true },
  );
}

function renderManager(props: { isFounder: boolean; characterId?: number; name?: string }) {
  return render(
    <CanonManager
      characterId={props.characterId ?? 7}
      isOwner
      isFounder={props.isFounder}
      characterName={props.name ?? 'Taylor'}
    />,
  );
}

const tab = (label: string) => screen.getByRole('tab', { name: label });
const tabs = () => screen.getAllByRole('tab').map((t) => t.textContent?.trim());

beforeEach(() => {
  vi.clearAllMocks();
  getIdentityCanon.mockResolvedValue(establishedCanon());
  patchFaceCanon.mockResolvedValue({});
  removeCanonBodyMark.mockResolvedValue({});
  addCanonBodyMark.mockResolvedValue({ mark: { id: 'm2' } });
  addCanonAccessory.mockResolvedValue({});
  removeCanonAccessory.mockResolvedValue({});
  patchBodyCanon.mockResolvedValue({});
});
afterEach(cleanup);

describe('Ordinary owner', () => {
  it('sees Face, Body, Accessories only, with tab semantics', async () => {
    renderManager({ isFounder: false });
    await screen.findByRole('tablist');
    expect(tabs()).toEqual(['Face', 'Body', 'Accessories']);
    expect(tab('Face').getAttribute('aria-selected')).toBe('true');
    expect(screen.getByRole('tabpanel')).toBeTruthy();
  });

  it('reads "Established" with what it means — editable, future images only — when both sections are locked', async () => {
    renderManager({ isFounder: false });
    await screen.findByText(/guides every new image/);
    expect(screen.getAllByText('Established').length).toBeGreaterThan(0);
    expect(screen.getByText(/changes affect future images, not ones already made/)).toBeTruthy();
    // No technical lock flags, no "Locked"/"Draft" vocabulary.
    expect(screen.queryByText(/Canon: locked/)).toBeNull();
    expect(screen.queryByText(/Face: locked/)).toBeNull();
    expect(screen.queryByText(/^Locked$/)).toBeNull();
    expect(screen.queryByText(/^Draft$/)).toBeNull();
  });

  it('reads "In progress" with the action to take when the canon is not fully locked', async () => {
    getIdentityCanon.mockResolvedValue(makeCanon());
    renderManager({ isFounder: false });
    await screen.findByText(/isn't established yet/);
    expect(screen.getAllByText('In progress').length).toBeGreaterThan(0);
    expect(screen.getByText(/Finish their setup from the Characters page/)).toBeTruthy();
  });

  it('sees the face references that exist, their notes, and can edit the notes even when locked', async () => {
    renderManager({ isFounder: false });
    await screen.findByRole('heading', { name: 'Face' });
    expect(screen.getByAltText('Front')).toBeTruthy();
    expect(screen.getByAltText('Left ¾')).toBeTruthy();
    // Populated slots only: no empty box, no upload.
    expect(screen.queryByText('Empty')).toBeNull();
    expect(screen.queryByText(/^Upload$/)).toBeNull();
    expect(screen.queryByText(/^Replace$/)).toBeNull();
    expect(screen.queryByAltText('Profile')).toBeNull();

    const notes = screen.getByLabelText('Face notes') as HTMLTextAreaElement;
    expect(notes.value).toBe('sharp jaw');
    expect(notes.disabled).toBe(false);
    fireEvent.change(notes, { target: { value: 'sharp jaw, grey eyes' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save notes' }));
    await waitFor(() => expect(patchFaceCanon).toHaveBeenCalledWith(7, { face_description: 'sharp jaw, grey eyes' }));
    await screen.findByText('Saved.');
    // Honest about reach: notes are not what guides new images.
    expect(screen.getByText(/New images are guided by the reference images above/)).toBeTruthy();
  });

  it('sees the body references that exist and the permanent marks, with the future-images consequence', async () => {
    renderManager({ isFounder: false });
    await screen.findByRole('tablist');
    fireEvent.click(tab('Body'));
    expect(screen.getByRole('heading', { name: 'Body' })).toBeTruthy();
    expect(screen.getByAltText('Body front')).toBeTruthy();
    expect(screen.getByAltText('Standing')).toBeTruthy();
    expect(screen.queryByText('Empty')).toBeNull();
    expect(screen.queryByText(/^Upload$/)).toBeNull();

    expect(screen.getByText('Permanent marks')).toBeTruthy();
    expect(screen.getByText(/Changes here affect future images only/)).toBeTruthy();
    expect(screen.getByText('Left sleeve')).toBeTruthy();
    expect(screen.getByText('Tattoo')).toBeTruthy();
  });

  it('can remove a permanent mark on an established (locked) character, and never sees an empty mark image slot', async () => {
    renderManager({ isFounder: false });
    await screen.findByRole('tablist');
    fireEvent.click(tab('Body'));
    fireEvent.click(screen.getByRole('button', { name: /Left sleeve/ }));
    expect(screen.queryByText('No image')).toBeNull();
    expect(screen.queryByText(/marking image/i)).toBeNull();
    expect(screen.getByText('Region: left full arm')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Remove Left sleeve' }));
    await waitFor(() => expect(removeCanonBodyMark).toHaveBeenCalledWith(7, 'm1'));
  });

  it('can add a permanent mark without an image; the description is what guides new images', async () => {
    renderManager({ isFounder: false });
    await screen.findByRole('tablist');
    fireEvent.click(tab('Body'));
    fireEvent.click(screen.getByRole('button', { name: 'Add permanent mark' }));
    expect(screen.queryByText(/marking image/i)).toBeNull();
    expect(screen.getByPlaceholderText(/this is what guides new images/)).toBeTruthy();
    fireEvent.change(screen.getByLabelText('Mark name'), { target: { value: 'Chin scar' } });
    fireEvent.change(screen.getByLabelText('Mark type'), { target: { value: 'scar' } });
    fireEvent.change(screen.getByLabelText('Body region'), { target: { value: 'jaw' } });
    fireEvent.click(screen.getByRole('button', { name: 'Add mark' }));
    await waitFor(() => expect(addCanonBodyMark).toHaveBeenCalledWith(7, expect.objectContaining({
      label: 'Chin scar', type: 'scar', body_region: 'jaw', description: 'Chin scar',
    })));
  });

  it('can manage the marked-skin declarations, in plain words', async () => {
    renderManager({ isFounder: false });
    await screen.findByRole('tablist');
    fireEvent.click(tab('Body'));
    expect(screen.getByText('Where marks appear')).toBeTruthy();
    expect(screen.getByText(/Not set — new images may put marks on any skin/)).toBeTruthy();
    expect(screen.queryByText(/Truth/)).toBeNull();
    expect(screen.queryByText(/generator/)).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: /Where marks appear/ }));
    fireEvent.click(screen.getByLabelText('Forearms'));
    fireEvent.click(screen.getByRole('button', { name: /Save mark regions/ }));
    await waitFor(() => expect(patchBodyCanon).toHaveBeenCalledWith(7, { marked_regions: ['forearms'] }));
  });

  it('sees accessories described as keyword-triggered signature items, and can add and remove them', async () => {
    getIdentityCanon.mockResolvedValue(establishedCanon({ accessories: [ACCESSORY] }));
    renderManager({ isFounder: false });
    await screen.findByRole('tablist');
    fireEvent.click(tab('Accessories'));
    expect(screen.getByText(/only when your prompt uses one of its keywords/)).toBeTruthy();
    expect(screen.getByText('Venetian mask')).toBeTruthy();
    expect(screen.getByText('Appears when you write:')).toBeTruthy();
    expect(screen.getByText('masked')).toBeTruthy();
    // No implementation vocabulary.
    expect(screen.queryByText(/Removable/)).toBeNull();
    expect(screen.queryByText(/inject/i)).toBeNull();
    expect(screen.queryByText(/[Tt]rigger/)).toBeNull();

    fireEvent.click(screen.getByRole('button', { name: 'Remove Venetian mask' }));
    await waitFor(() => expect(removeCanonAccessory).toHaveBeenCalledWith(7, 'a1'));

    fireEvent.click(screen.getByRole('button', { name: 'Add accessory' }));
    fireEvent.change(screen.getByLabelText('Accessory name'), { target: { value: 'Round glasses' } });
    fireEvent.change(screen.getByLabelText('Accessory type'), { target: { value: 'glasses' } });
    fireEvent.change(screen.getByLabelText('How it looks'), { target: { value: 'thin gold round glasses' } });
    fireEvent.change(screen.getByLabelText('Keywords that bring it in'), { target: { value: 'glasses, spectacles' } });
    fireEvent.click(screen.getByRole('button', { name: 'Add accessory' }));
    await waitFor(() => expect(addCanonAccessory).toHaveBeenCalledWith(7, {
      label: 'Round glasses', type: 'glasses', description: 'thin gold round glasses',
      trigger_keywords: ['glasses', 'spectacles'],
    }));
  });

  it('never sees lock controls, empty slots or Scene Images on any tab, and no copy names Scene Images', async () => {
    getIdentityCanon.mockResolvedValue(makeCanon());
    renderManager({ isFounder: false });
    await screen.findByRole('tablist');
    for (const label of ['Face', 'Body', 'Accessories']) {
      fireEvent.click(tab(label));
      expect(screen.queryByText(/Lock Face Canon|Lock Body Canon/)).toBeNull();
      expect(screen.queryByText('Empty')).toBeNull();
      expect(screen.queryByText(/^Upload$|^Replace$/)).toBeNull();
      expect(screen.queryByText(/Scene Images|Generate Scene/)).toBeNull();
    }
    // With nothing generated yet, the owner is told why, not shown ten empty boxes.
    fireEvent.click(tab('Face'));
    expect(screen.getByText(/No face references yet/)).toBeTruthy();
    fireEvent.click(tab('Body'));
    expect(screen.getByText(/No body references yet/)).toBeTruthy();
  });
});

describe('Founder', () => {
  it('sees every slot with Upload, the lock buttons, the lock-flag status bar and Scene Images', async () => {
    getIdentityCanon.mockResolvedValue(makeCanon({}, { face_front_image_url: '/f.png' }));
    renderManager({ isFounder: true });
    await screen.findByText(/Canon: draft/);
    expect(tabs()).toEqual(['Face', 'Body', 'Accessories', 'Scene Images']);
    expect(screen.getByText(/Face: draft/)).toBeTruthy();
    expect(screen.getByText(/Body: draft/)).toBeTruthy();
    // All five face slots: one image, four empty, upload/replace on each.
    expect(screen.getAllByText('Empty')).toHaveLength(4);
    expect(screen.getAllByText('Upload')).toHaveLength(4);
    expect(screen.getByText('Replace')).toBeTruthy();
    expect(screen.getByRole('button', { name: /Lock Face Canon/ })).toBeTruthy();
    fireEvent.click(tab('Body'));
    expect(screen.getAllByText('Empty')).toHaveLength(10);
    expect(screen.getByRole('button', { name: /Lock Body Canon/ })).toBeTruthy();
  });

  it('reads a truthful lock explainer once locked — established, still editable, future images only', async () => {
    renderManager({ isFounder: true });
    await screen.findByText(/Canon: locked/);
    expect(screen.getByText(/Face is locked: it counts as established and guides new images/)).toBeTruthy();
    expect(screen.getByText(/Slots and notes stay editable; edits affect future images only/)).toBeTruthy();
    expect(screen.queryByText(/locked in as the reference for every image generated from now on/)).toBeNull();
  });

  it('retains the mark image upload on a mark and in the add form', async () => {
    renderManager({ isFounder: true });
    await screen.findByText(/Canon: locked/);
    fireEvent.click(tab('Body'));
    fireEvent.click(screen.getByRole('button', { name: /Left sleeve/ }));
    expect(screen.getByText('No image')).toBeTruthy();
    expect(screen.getByText('Upload marking image')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Add permanent mark' }));
    expect(screen.getByText(/Marking image \(required\)/)).toBeTruthy();
  });
});

describe('Stale state and character switching', () => {
  it('a stale "scenes" tab falls back to Face when founder access is lost, and cannot be forced back', async () => {
    const view = renderManager({ isFounder: true });
    await screen.findByText(/Canon: locked/);
    fireEvent.click(tab('Scene Images'));
    expect(screen.getByText('Generate Scene')).toBeTruthy();
    view.rerender(<CanonManager characterId={7} isOwner isFounder={false} characterName="Taylor" />);
    expect(screen.queryByRole('tab', { name: 'Scene Images' })).toBeNull();
    expect(screen.queryByText('Generate Scene')).toBeNull();
    expect(screen.getByRole('heading', { name: 'Face' })).toBeTruthy();
    expect(tab('Face').getAttribute('aria-selected')).toBe('true');
  });

  it('changing character drops the previous canon immediately and shows the new one', async () => {
    const canonA = establishedCanon();
    const canonB = makeCanon({ character_id: 8 }, { face_description: 'round face' });
    getIdentityCanon.mockImplementation((id: number) => Promise.resolve(id === 7 ? canonA : canonB));
    const view = renderManager({ isFounder: false, characterId: 7, name: 'Taylor' });
    await screen.findByAltText('Front');
    // A notes draft typed for Taylor…
    fireEvent.change(screen.getByLabelText('Face notes'), { target: { value: 'unsaved for Taylor' } });

    view.rerender(<CanonManager characterId={8} isOwner isFounder={false} characterName="Morgan" />);
    // …is gone with Taylor's images, before Morgan's canon has even loaded.
    expect(screen.queryByAltText('Front')).toBeNull();
    expect(screen.queryByDisplayValue('unsaved for Taylor')).toBeNull();
    await screen.findByText(/Morgan's Character Canon isn't established yet/);
    expect((screen.getByLabelText('Face notes') as HTMLTextAreaElement).value).toBe('round face');
    expect(getIdentityCanon).toHaveBeenLastCalledWith(8);
  });

  it('a slow response for the previous character cannot land on the new one', async () => {
    let resolveA: (v: unknown) => void = () => {};
    const slowA = new Promise((r) => { resolveA = r; });
    const canonB = makeCanon({ character_id: 8 }, { face_description: 'round face' });
    getIdentityCanon.mockImplementation((id: number) => (id === 7 ? slowA : Promise.resolve(canonB)));

    const view = renderManager({ isFounder: false, characterId: 7, name: 'Taylor' });
    await screen.findByRole('status'); // Loading canon…
    view.rerender(<CanonManager characterId={8} isOwner isFounder={false} characterName="Morgan" />);
    await screen.findByText(/Morgan's Character Canon isn't established yet/);

    // Now A's answer arrives — established, with a front image.
    resolveA(establishedCanon());
    await new Promise((r) => setTimeout(r, 0));
    expect(screen.queryByAltText('Front')).toBeNull();
    expect(screen.queryByText(/guides every new image/)).toBeNull();
    expect((screen.getByLabelText('Face notes') as HTMLTextAreaElement).value).toBe('round face');
  });
});

describe('Establishing canon (addendum A) and the shared status (addendum B)', () => {
  /** The abandoned-pack state: every card generated, lock step never reached. */
  function abandonedPack() {
    return makeCanon(
      { status: 'draft', face_locked: false, body_locked: false },
      { face_front_image_url: '/f.png', face_left_3q_image_url: '/l.png' },
      { body_front_image_url: '/b.png' },
    );
  }

  it('owner with a complete canon but visual_locked=false reads "In progress" and is offered Establish Character Canon', async () => {
    getIdentityCanon.mockResolvedValue(abandonedPack());
    render(<CanonManager characterId={7} isOwner isFounder={false} characterName="Taylor" ownerStatus="unfinished" />);
    await screen.findByText('In progress');
    expect(screen.getByRole('button', { name: 'Establish Character Canon' })).toBeTruthy();
    expect(screen.getByText(/ready to guide new images/)).toBeTruthy();
    expect(screen.getByText(/You can still edit the canon afterwards; changes affect future images only/)).toBeTruthy();
    // Owner-facing action only: no per-section founder lock controls.
    expect(screen.queryByText(/Lock Face Canon|Lock Body Canon/)).toBeNull();
  });

  it('an already-established owner is not offered the action', async () => {
    render(<CanonManager characterId={7} isOwner isFounder={false} characterName="Taylor" ownerStatus="established" />);
    await screen.findByText('Established');
    expect(screen.queryByRole('button', { name: 'Establish Character Canon' })).toBeNull();
  });

  it('founder controls are unchanged: Lock Face/Body Canon, no owner action', async () => {
    getIdentityCanon.mockResolvedValue(abandonedPack());
    render(<CanonManager characterId={7} isOwner isFounder characterName="Taylor" ownerStatus="unfinished" />);
    await screen.findByText(/Canon: draft/);
    expect(screen.queryByRole('button', { name: 'Establish Character Canon' })).toBeNull();
    expect(screen.getByRole('button', { name: /Lock Face Canon/ })).toBeTruthy();
  });

  it('establishing calls the two existing lock routes, re-reads the canon, shows Established and reports up', async () => {
    let locked = false;
    getIdentityCanon.mockImplementation(() => Promise.resolve(locked
      ? makeCanon({ status: 'locked', face_locked: true, body_locked: true }, { face_front_image_url: '/f.png' }, { body_front_image_url: '/b.png' })
      : abandonedPack()));
    lockFaceCanon.mockResolvedValue({});
    lockBodyCanon.mockImplementation(() => { locked = true; return Promise.resolve({}); });
    const onEstablished = vi.fn();
    render(<CanonManager characterId={7} isOwner isFounder={false} characterName="Taylor" ownerStatus="unfinished" onEstablished={onEstablished} />);
    fireEvent.click(await screen.findByRole('button', { name: 'Establish Character Canon' }));
    await screen.findByText('Established');
    expect(lockFaceCanon).toHaveBeenCalledWith(7);
    expect(lockBodyCanon).toHaveBeenCalledWith(7);
    expect(onEstablished).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole('button', { name: 'Establish Character Canon' })).toBeNull();
    expect(screen.getByText(/guides every new image/)).toBeTruthy();
  });

  it('a partial failure shows the server error, does not claim Established, and a retry repeats only the failed section', async () => {
    // Face locks; body refuses once. The re-read shows face locked, body not.
    let bodyAttempts = 0;
    let faceLocked = false;
    let bodyLocked = false;
    getIdentityCanon.mockImplementation(() => Promise.resolve(makeCanon(
      { status: faceLocked && bodyLocked ? 'locked' : 'draft', face_locked: faceLocked, body_locked: bodyLocked },
      { face_front_image_url: '/f.png' }, { body_front_image_url: '/b.png' },
    )));
    lockFaceCanon.mockImplementation(() => { faceLocked = true; return Promise.resolve({}); });
    lockBodyCanon.mockImplementation(() => {
      bodyAttempts += 1;
      if (bodyAttempts === 1) return Promise.reject(new Error('body_front_image_url is required to lock body canon'));
      bodyLocked = true;
      return Promise.resolve({});
    });
    const onEstablished = vi.fn();
    render(<CanonManager characterId={7} isOwner isFounder={false} characterName="Taylor" ownerStatus="unfinished" onEstablished={onEstablished} />);
    fireEvent.click(await screen.findByRole('button', { name: 'Establish Character Canon' }));
    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toMatch(/Could not establish Taylor's canon \(body: body_front_image_url is required/);
    expect(screen.getByText('In progress')).toBeTruthy();
    expect(screen.queryByText('Established')).toBeNull();
    expect(onEstablished).not.toHaveBeenCalled();
    expect(lockFaceCanon).toHaveBeenCalledTimes(1);

    // Retry: face is already locked per the re-read, so only body is called.
    fireEvent.click(screen.getByRole('button', { name: 'Establish Character Canon' }));
    await screen.findByText('Established');
    expect(lockFaceCanon).toHaveBeenCalledTimes(1);
    expect(lockBodyCanon).toHaveBeenCalledTimes(2);
    expect(onEstablished).toHaveBeenCalledTimes(1);
  });

  it('a pack that stopped before the body reference is told the truth, with no invented recovery', async () => {
    getIdentityCanon.mockResolvedValue(makeCanon({}, { face_front_image_url: '/f.png' }));
    render(<CanonManager characterId={7} isOwner isFounder={false} characterName="Taylor" ownerStatus="unfinished" />);
    await screen.findByText('In progress');
    expect(screen.queryByRole('button', { name: 'Establish Character Canon' })).toBeNull();
    expect(screen.getByText(/reference set is incomplete/)).toBeTruthy();
    expect(screen.getByText(/Contact Ficshon/)).toBeTruthy();
  });

  it('a true draft (no canon at all) is sent to finish setup', async () => {
    getIdentityCanon.mockResolvedValue(makeCanon());
    render(<CanonManager characterId={7} isOwner isFounder={false} characterName="Taylor" ownerStatus="unfinished" />);
    await screen.findByText('In progress');
    expect(screen.queryByRole('button', { name: 'Establish Character Canon' })).toBeNull();
    expect(screen.getByText(/Finish their setup from the Characters page/)).toBeTruthy();
  });

  it('a legacy character (visual_locked, no v2 canon) reads "Needs attention" — never Established — with a remediation', async () => {
    getIdentityCanon.mockResolvedValue(makeCanon());
    render(<CanonManager characterId={7} isOwner isFounder={false} characterName="Taylor" ownerStatus="legacy" />);
    await screen.findByText('Needs attention');
    expect(screen.queryByText('Established')).toBeNull();
    expect(screen.queryByText('In progress')).toBeNull();
    expect(screen.queryByRole('button', { name: 'Establish Character Canon' })).toBeNull();
    expect(screen.getByText(/set up before Character Canon existed/)).toBeTruthy();
    expect(screen.getByText(/Contact Ficshon/)).toBeTruthy();
  });

  it('the state matrix: the manager agrees with the page-level status in every state', async () => {
    const cases: { ownerStatus: 'established' | 'unfinished' | 'legacy'; canon: ReturnType<typeof makeCanon>; word: string }[] = [
      { ownerStatus: 'unfinished', canon: makeCanon(), word: 'In progress' },
      { ownerStatus: 'unfinished', canon: abandonedPack(), word: 'In progress' },
      { ownerStatus: 'established', canon: establishedCanon(), word: 'Established' },
      { ownerStatus: 'legacy', canon: makeCanon(), word: 'Needs attention' },
      // Partially-bridged legacy canon: the page says established (the guard
      // admits it and the server has content); the manager must not contradict it.
      { ownerStatus: 'established', canon: makeCanon({ face_locked: true }, { face_front_image_url: '/f.png', locked: true }), word: 'Established' },
    ];
    for (const c of cases) {
      getIdentityCanon.mockResolvedValue(c.canon);
      const view = render(<CanonManager characterId={7} isOwner isFounder={false} characterName="Taylor" ownerStatus={c.ownerStatus} />);
      await screen.findByText(c.word);
      for (const other of ['Established', 'In progress', 'Needs attention'].filter((w) => w !== c.word)) {
        expect(screen.queryByText(other), `${c.ownerStatus}: ${other}`).toBeNull();
      }
      view.unmount();
    }
  });
});

describe('Source-level pins', () => {
  it('no owner_id comparison decides ownership; isOwner is a prop', () => {
    expect(canonManagerSource).not.toMatch(/owner_id/);
    expect(characterDetailSource).toMatch(/character\.is_owner === true/);
  });

  it('no backend-enforced lock is introduced: lock routes are the only lock calls, and no edit is gated on the lock', () => {
    // The only lock mutations: the two founder buttons and the owner's
    // Establish action, all through the existing owner-authorised routes.
    expect(canonManagerSource.match(/lockFaceCanon\(/g)).toHaveLength(2);
    expect(canonManagerSource.match(/lockBodyCanon\(/g)).toHaveLength(2);
    // No other endpoint is involved in establishing — in particular nothing
    // that generates (no provider call).
    const establish = canonManagerSource.slice(canonManagerSource.indexOf('async function establish()'), canonManagerSource.indexOf('const word ='));
    expect(establish.match(/apiClient\.\w+/g)).toEqual(['apiClient.lockFaceCanon', 'apiClient.lockBodyCanon']);
    // No control is disabled or hidden because the section is locked.
    expect(canonManagerSource).not.toMatch(/disabled=\{canon\.(face|body)_locked/);
    expect(canonManagerSource).not.toMatch(/\{!canon\.body_locked && \(\s*<button/);
  });

  it('ordinary-owner guard copy names no implementation terms', () => {
    const guardCopy = sceneGeneratorSource.slice(sceneGeneratorSource.indexOf('{lockedGuardActive && ('), sceneGeneratorSource.indexOf('<div className="flex flex-wrap items-center justify-between'));
    expect(guardCopy).not.toMatch(/identity anchor|anchor JSON|identity pack|lock your/i);
    expect(guardCopy).toMatch(/Character Canon/);
  });
});
