// @vitest-environment jsdom
//
// StepSketch and the Sketch allowance (Polish Phase 2, C10): what the creator
// sees is always the server's number; zero never strands them.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';

const api = vi.hoisted(() => ({
  getSketchAllowance: vi.fn(),
  generateIdentitySketch: vi.fn(),
}));
vi.mock('../../shared/api', async (importOriginal) => {
  const original = await importOriginal<typeof import('../../shared/api')>();
  return { ...original, ...api };
});

import StepSketch from '../StepSketch';
import { ApiError } from '../../shared/api';
import type { SketchAllowance } from '../../shared/types';

afterEach(cleanup);
beforeEach(() => {
  api.getSketchAllowance.mockReset();
  api.generateIdentitySketch.mockReset();
  // jsdom never loads images; resolve the preload immediately.
  Object.defineProperty(globalThis.Image.prototype, 'src', {
    set() { setTimeout(() => this.onload?.(new Event('load')), 0); },
    configurable: true,
  });
});

const allow = (over: Partial<SketchAllowance> = {}): SketchAllowance => ({
  limit: 3, used: 0, remaining: 3, allowed: true, window_hours: 24, next_available_at: null, ...over,
});

function renderStep() {
  const onConfirmed = vi.fn();
  render(
    <StepSketch
      characterId={7}
      identitySpec={{ gender: 'female', age_band: '26-35', identity: {} } as never}
      onConfirmed={onConfirmed}
      onBack={() => {}}
      activeCreationCharacterId={7}
    />,
  );
  return { onConfirmed };
}

describe('StepSketch allowance', () => {
  it('loads the allowance and shows the remaining count', async () => {
    api.getSketchAllowance.mockResolvedValue(allow({ used: 1, remaining: 2 }));
    renderStep();
    expect(api.getSketchAllowance).toHaveBeenCalledWith(7);
    await waitFor(() => expect(screen.getByTestId('sketch-allowance').textContent).toBe('2 sketch attempts remaining'));
    expect(screen.getByRole('button', { name: /Generate sketch/ })).toHaveProperty('disabled', false);
  });

  it('shows the allowance the generate response carries — not a local decrement', async () => {
    api.getSketchAllowance.mockResolvedValue(allow());
    api.generateIdentitySketch.mockResolvedValue({
      image_url: '/static/generated/x.png', image_id: 1, style: 'pencil', prompt_preview: 'p',
      allowance: allow({ used: 2, remaining: 1 }),  // another tab spent one meanwhile
    });
    renderStep();
    await waitFor(() => screen.getByTestId('sketch-allowance'));
    fireEvent.click(screen.getByRole('button', { name: /Generate sketch/ }));
    await waitFor(() => expect(screen.getByTestId('sketch-allowance').textContent).toBe('1 sketch attempt remaining'));
    expect(screen.getByRole('button', { name: /Try again/ })).toBeTruthy();
    expect(api.getSketchAllowance).toHaveBeenCalledTimes(1);
  });

  it('refetches when the generate response has no allowance', async () => {
    api.getSketchAllowance.mockResolvedValueOnce(allow()).mockResolvedValueOnce(allow({ used: 1, remaining: 2 }));
    api.generateIdentitySketch.mockResolvedValue({ image_url: '/x.png', image_id: 1, style: 'pencil', prompt_preview: 'p' });
    renderStep();
    await waitFor(() => screen.getByTestId('sketch-allowance'));
    fireEvent.click(screen.getByRole('button', { name: /Generate sketch/ }));
    await waitFor(() => expect(screen.getByTestId('sketch-allowance').textContent).toBe('2 sketch attempts remaining'));
    expect(api.getSketchAllowance).toHaveBeenCalledTimes(2);
  });

  it('at zero: no Generate/Try again, an honest notice, and Skip still works', async () => {
    api.getSketchAllowance.mockResolvedValue(
      allow({ used: 3, remaining: 0, allowed: false, next_available_at: new Date(Date.now() + 3 * 3600_000).toISOString() }),
    );
    const { onConfirmed } = renderStep();
    await waitFor(() => screen.getByText(/You've used your 3 sketch attempts for now/));
    expect(screen.getByText(/another opens in about 3 hours/)).toBeTruthy();
    expect(screen.queryByRole('button', { name: /Generate sketch|Try again/ })).toBeNull();
    expect(screen.getByText(/The sketch is optional/)).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: /Skip the sketch/ }));
    expect(onConfirmed).toHaveBeenCalledTimes(1);
    expect(api.generateIdentitySketch).not.toHaveBeenCalled();
  });

  it("reconciles to the server's exhausted state on a 429 instead of showing an error", async () => {
    api.getSketchAllowance.mockResolvedValue(allow({ used: 2, remaining: 1 }));
    api.generateIdentitySketch.mockRejectedValue(
      new ApiError('spent', 429, { error: 'sketch_allowance_exhausted', allowance: allow({ used: 3, remaining: 0, allowed: false }) }),
    );
    renderStep();
    await waitFor(() => screen.getByTestId('sketch-allowance'));
    fireEvent.click(screen.getByRole('button', { name: /Generate sketch/ }));
    await waitFor(() => screen.getByText(/You've used your 3 sketch attempts for now/));
    expect(screen.queryByRole('alert')).toBeNull();
    expect(screen.queryByRole('button', { name: /Generate sketch|Try again/ })).toBeNull();
  });

  it('shows a provider failure as a failure, with the allowance untouched', async () => {
    api.getSketchAllowance.mockResolvedValue(allow({ used: 1, remaining: 2 }));
    api.generateIdentitySketch.mockRejectedValue(new ApiError('Sketch generation is temporarily unavailable.', 503, { detail: 'x' }));
    renderStep();
    await waitFor(() => screen.getByTestId('sketch-allowance'));
    fireEvent.click(screen.getByRole('button', { name: /Generate sketch/ }));
    await waitFor(() => screen.getByRole('alert'));
    expect(screen.getByRole('alert').textContent).toMatch(/temporarily unavailable/);
    expect(screen.getByTestId('sketch-allowance').textContent).toBe('2 sketch attempts remaining');
    expect(screen.getByRole('button', { name: /Generate sketch/ })).toBeTruthy();
  });

  it('does not strand the creator if the allowance cannot be read', async () => {
    api.getSketchAllowance.mockRejectedValue(new Error('offline'));
    renderStep();
    await waitFor(() => expect(screen.getByRole('button', { name: /Generate sketch/ })).toHaveProperty('disabled', false));
    expect(screen.queryByTestId('sketch-allowance')).toBeNull();
    expect(screen.getByRole('button', { name: /Skip the sketch/ })).toBeTruthy();
  });

  it('keeps the Phase 1 truth copy', async () => {
    api.getSketchAllowance.mockResolvedValue(allow());
    renderStep();
    expect(screen.getByText(/generated from your answers, not from this sketch/)).toBeTruthy();
  });
});
