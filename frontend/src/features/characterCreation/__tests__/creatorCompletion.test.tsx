// @vitest-environment jsdom
/**
 * Creator completion and the reference-image step — Polish Phase 5.8.
 *
 * StepDossierLock still establishes the canon exactly as before: the two
 * owner-authorised lock routes, face then body, automatically, with no
 * provider involved. Only the words changed — the user reads "Establishing
 * Character Canon…" and "Character Canon established", never "lock". A
 * failure is reported truthfully with a safe Try again (both routes are
 * idempotent). StepGeneratePack never offers a "Regenerate" that the server
 * would turn into a no-op (finished slots are skipped): it offers to make
 * the missing images, and Next waits for the two front images the lock
 * routes require, so the Creator cannot walk into a 409 at the last step.
 */
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const lockFaceCanon = vi.fn();
const lockBodyCanon = vi.fn();
const startV2PackJob = vi.fn();
const getLatestV2PackJob = vi.fn();
const patchBodyCanon = vi.fn();

vi.mock('../shared/api', () => ({
  lockFaceCanon: (...a: unknown[]) => lockFaceCanon(...a),
  lockBodyCanon: (...a: unknown[]) => lockBodyCanon(...a),
  startV2PackJob: (...a: unknown[]) => startV2PackJob(...a),
  getV2PackJob: vi.fn(),
  getLatestV2PackJob: (...a: unknown[]) => getLatestV2PackJob(...a),
  patchBodyCanon: (...a: unknown[]) => patchBodyCanon(...a),
  generateIdentityPack: vi.fn(),
  resolveImageUrl: (u: string) => u,
}));

import StepDossierLock from '../steps/StepDossierLock';
import StepGeneratePack from '../steps/StepGeneratePack';
import { DEFAULT_BODY_MORPHOLOGY, STEP_LABELS } from '../shared/types';
import type { V2PackResponse } from '../shared/types';
import dossierSource from '../steps/StepDossierLock.tsx?raw';

const ALL_SLOTS = [
  'face_front', 'face_left_3q', 'face_right_3q', 'face_profile', 'face_expression',
  'body_front', 'body_left', 'body_right', 'body_back',
  'torso_front', 'torso_side', 'standing_relaxed', 'seated_relaxed',
];

function pack(withUrls: string[]): V2PackResponse {
  return {
    pack_id: 'p1', dry_run: false, image_count: withUrls.length, total_spend: 0,
    cards: ALL_SLOTS.map((slot) => ({
      slot, section: slot.startsWith('face') ? 'face' : 'body', role: slot,
      url: withUrls.includes(slot) ? `/${slot}.png` : null,
      status: withUrls.includes(slot) ? 'generated' : 'error',
    })),
    marks: [], regenerations: [], openai_fallback: [], gate_failed: [], errors: [], clean_pass: false,
  } as unknown as V2PackResponse;
}

beforeEach(() => {
  vi.clearAllMocks();
  lockFaceCanon.mockResolvedValue({});
  lockBodyCanon.mockResolvedValue({});
  getLatestV2PackJob.mockResolvedValue(null);
  patchBodyCanon.mockResolvedValue({});
  startV2PackJob.mockResolvedValue({ job_id: 'j1', status: 'queued' });
});
afterEach(cleanup);

describe('StepDossierLock — establishing Character Canon', () => {
  const renderStep = () =>
    render(
      <MemoryRouter>
        <StepDossierLock characterId={42} pack={pack(ALL_SLOTS)} selectedIndex={0} basics={{ name: 'Taylor', alias: '' }} />
      </MemoryRouter>,
    );

  it('calls the same two lock routes, face then body, automatically, and reads as product language', async () => {
    renderStep();
    expect(screen.getByRole('status').textContent).toMatch(/Establishing Character Canon…/);
    await screen.findByRole('heading', { name: 'Character Canon established' });
    expect(lockFaceCanon).toHaveBeenCalledWith(42);
    expect(lockBodyCanon).toHaveBeenCalledWith(42);
    expect(lockFaceCanon.mock.invocationCallOrder[0]).toBeLessThan(lockBodyCanon.mock.invocationCallOrder[0]);
    expect(screen.getByText(/will guide every new image of them/)).toBeTruthy();
    expect(screen.getByText(/refine it any time from their page/)).toBeTruthy();
    expect(document.body.textContent).not.toMatch(/Identity Locked|Locking identity|lock/i);
    expect(screen.getByRole('button', { name: 'Bring Taylor to life' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'View Character' })).toBeTruthy();
  });

  it('reports a failure truthfully and Try again repeats the same routes', async () => {
    lockBodyCanon.mockRejectedValueOnce(new Error('body_front_image_url is required to lock body canon'));
    renderStep();
    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toMatch(/couldn't establish Taylor's Character Canon \(body_front_image_url is required/);
    expect(screen.queryByRole('heading', { name: 'Character Canon established' })).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'Try again' }));
    await screen.findByRole('heading', { name: 'Character Canon established' });
    expect(lockFaceCanon).toHaveBeenCalledTimes(2);
    expect(lockBodyCanon).toHaveBeenCalledTimes(2);
  });

  it('completion touches only the two lock routes — no provider, no generation (source pin)', () => {
    const calls = dossierSource.match(/await \w+\(/g) ?? [];
    expect(calls).toEqual(['await lockFaceCanon(', 'await lockBodyCanon(']);
    // Nothing else is imported from the API module.
    const apiImport = dossierSource.match(/import \{([^}]*)\} from '\.\.\/shared\/api'/)?.[1] ?? '';
    expect(apiImport.split(',').map((s) => s.trim()).sort()).toEqual(['lockBodyCanon', 'lockFaceCanon', 'resolveImageUrl']);
  });

  it('step labels use the product vocabulary', () => {
    expect(STEP_LABELS).toEqual(['Interview', 'Sketch', 'Reference images', 'Choose portrait', 'Character Canon']);
  });
});

describe('StepGeneratePack — the reference images', () => {
  const renderStep = (p: V2PackResponse | null, onNext = vi.fn()) =>
    render(
      <StepGeneratePack
        characterId={42}
        identitySpec={null}
        bodyMorphology={DEFAULT_BODY_MORPHOLOGY}
        onBodyMorphologyChange={() => {}}
        pack={p}
        onPackGenerated={() => {}}
        onNext={onNext}
        onBack={() => {}}
      />,
    );

  it('with no reference images yet: offers to make them; Next is disabled', async () => {
    renderStep(null);
    expect(screen.getByRole('button', { name: 'Make the reference images' })).toBeTruthy();
    expect((screen.getByRole('button', { name: 'Next' }) as HTMLButtonElement).disabled).toBe(true);
    expect(document.body.textContent).not.toMatch(/Identity Pack|canon pack|Locking/);
  });

  it('with a complete set: no make/regenerate button (the server would skip every slot); Next enabled', async () => {
    renderStep(pack(ALL_SLOTS));
    await waitFor(() => expect(getLatestV2PackJob).toHaveBeenCalled());
    expect(screen.queryByRole('button', { name: /Regenerate|Make the reference images|Finish the reference images/ })).toBeNull();
    expect((screen.getByRole('button', { name: 'Next' }) as HTMLButtonElement).disabled).toBe(false);
  });

  it('C — face made, body front missing: offers to finish only the missing images and holds Next', async () => {
    const onNext = vi.fn();
    renderStep(pack(['face_front', 'face_left_3q', 'face_right_3q', 'face_profile', 'face_expression']), onNext);
    const finish = await screen.findByRole('button', { name: 'Finish the reference images (8 missing)' });
    expect((screen.getByRole('button', { name: 'Next' }) as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByRole('status').textContent).toMatch(/front face and front body images are needed before Next/);
    // Finishing goes through the existing job route — the same one first
    // generation uses; the server skips finished slots. No direct provider call.
    fireEvent.click(finish);
    await waitFor(() => expect(startV2PackJob).toHaveBeenCalledTimes(1));
    expect(startV2PackJob.mock.calls[0][0]).toBe(42);
    expect(patchBodyCanon).toHaveBeenCalledWith(42, expect.objectContaining({ height: expect.any(String) }));
  });

  it('D-ish — both fronts present, a side card missing: Next is allowed and Finish is still offered', async () => {
    renderStep(pack(ALL_SLOTS.filter((s) => s !== 'seated_relaxed')));
    await screen.findByRole('button', { name: 'Finish the reference images (1 missing)' });
    expect((screen.getByRole('button', { name: 'Next' }) as HTMLButtonElement).disabled).toBe(false);
    expect(screen.queryByRole('status')).toBeNull();
  });
});
