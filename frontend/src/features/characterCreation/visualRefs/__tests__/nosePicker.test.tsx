// @vitest-environment jsdom
//
// The Nose picker (Polish Phase 3C, assets installed in Phase 3). Face shape
// is the picker's reference test; this pins the Nose category on the same
// shared component — six cards, the exact stored values, the toggle/clear
// semantics and both example sets' asset paths — so the installed images
// and the wired field cannot drift apart unnoticed.
import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';

import VisualFeaturePicker from '../VisualFeaturePicker';
import { NOSE_CATEGORY, type ExampleSet, type NoseValue } from '../refCatalog';
import { refAssetUrl } from '../refAssetUrl';
import { NOSE_TYPES } from '../../shared/types';

afterEach(cleanup);

const VALUES = ['straight', 'narrow', 'broad', 'hooked', 'roman', 'upturned'] as const;
const LABELS = ['Straight', 'Narrow', 'Broad', 'Hooked', 'Roman', 'Upturned'] as const;

function renderNose(value: NoseValue | undefined = undefined, set: ExampleSet = 'feminine') {
  const onChange = vi.fn();
  render(
    <VisualFeaturePicker
      category={NOSE_CATEGORY}
      ariaLabel="Nose"
      value={value}
      onChange={onChange}
      exampleSet={set}
    />,
  );
  return { onChange, group: screen.getByRole('group', { name: 'Nose' }) };
}

describe('VisualFeaturePicker — nose', () => {
  it('is keyed to the nose_type spec field and uses the Interview vocabulary unchanged', () => {
    expect(NOSE_CATEGORY.key).toBe('nose_type');
    expect(NOSE_CATEGORY.options).toBe(NOSE_TYPES);
    expect(NOSE_CATEGORY.options.map((o) => o.value)).toEqual(VALUES);
    expect(NOSE_CATEGORY.options.map((o) => o.label)).toEqual(LABELS);
  });

  it('renders six cards, three across, each with its human-readable label and a hint', () => {
    const { group } = renderNose();
    expect(group.className).toContain('grid-cols-3');
    const buttons = within(group).getAllByRole('button');
    expect(buttons).toHaveLength(6);
    expect(buttons.map((b) => b.textContent)).toEqual(LABELS.map((l) => expect.stringContaining(l)));
    for (const b of buttons) expect(b.getAttribute('aria-pressed')).toBe('false');
    expect(within(group).getByText('Curves down')).toBeTruthy(); // hooked
  });

  it('writes the exact stored DNA value for every card', () => {
    const { onChange, group } = renderNose();
    VALUES.forEach((value, i) => {
      fireEvent.click(within(group).getByRole('button', { name: new RegExp(LABELS[i]) }));
      expect(onChange).toHaveBeenLastCalledWith(value);
    });
    expect(onChange).toHaveBeenCalledTimes(6);
  });

  it('shows an already-stored value as the pressed card (resume / edit)', () => {
    const { group } = renderNose('roman');
    const roman = within(group).getByRole('button', { name: /Roman/ });
    expect(roman.getAttribute('aria-pressed')).toBe('true');
    expect(roman.querySelector('svg')).toBeTruthy(); // tick badge
    expect(roman.className).toContain('border-gem');
    const others = within(group).getAllByRole('button').filter((b) => b !== roman);
    expect(others).toHaveLength(5);
    for (const b of others) expect(b.getAttribute('aria-pressed')).toBe('false');
  });

  it('clears on re-press of the active card and switches on press of another — the shared picker semantics', () => {
    const { onChange, group } = renderNose('hooked');
    fireEvent.click(within(group).getByRole('button', { name: /Hooked/ }));
    expect(onChange).toHaveBeenLastCalledWith(undefined);
    fireEvent.click(within(group).getByRole('button', { name: /Upturned/ }));
    expect(onChange).toHaveBeenLastCalledWith('upturned');
  });

  it('points every card at the feminine and masculine asset paths', () => {
    for (const set of ['feminine', 'masculine'] as const) {
      const { group } = renderNose(undefined, set);
      const srcs = [...group.querySelectorAll('img')].map((i) => i.getAttribute('src'));
      expect(srcs).toEqual(VALUES.map((v) => `/creator-refs/nose_type/${set}/${v}.webp`));
      expect(srcs).toEqual(VALUES.map((v) => refAssetUrl('nose_type', set, v)));
      cleanup();
    }
  });

  it('degrades to the neutral tile with the label intact when an image is missing', () => {
    const { group } = renderNose();
    const broad = within(group).getByRole('button', { name: /Broad/ });
    fireEvent.error(broad.querySelector('img') as HTMLImageElement);
    expect(broad.querySelector('img')).toBeNull();
    expect(within(broad).getByTestId('ref-placeholder')).toBeTruthy();
    expect(within(broad).getByText('Broad')).toBeTruthy();
  });
});
