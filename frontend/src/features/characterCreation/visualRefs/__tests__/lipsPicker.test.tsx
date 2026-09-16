// @vitest-environment jsdom
//
// The Lips picker (Polish Phase 3C, assets installed in Phase 3). The last
// of the six core reference-card categories, pinned on the shared component
// the same way as Nose: four cards, the exact stored values, the
// toggle/clear semantics and both example sets' asset paths.
import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';

import VisualFeaturePicker from '../VisualFeaturePicker';
import { LIP_CATEGORY, type ExampleSet, type LipValue } from '../refCatalog';
import { refAssetUrl } from '../refAssetUrl';
import { LIP_TYPES } from '../../shared/types';

afterEach(cleanup);

const VALUES = ['thin', 'balanced', 'full', 'cupid_bow'] as const;
const LABELS = ['Thin', 'Balanced', 'Full', 'Cupid bow'] as const;

function renderLips(value: LipValue | undefined = undefined, set: ExampleSet = 'feminine') {
  const onChange = vi.fn();
  render(
    <VisualFeaturePicker
      category={LIP_CATEGORY}
      ariaLabel="Lips"
      value={value}
      onChange={onChange}
      exampleSet={set}
    />,
  );
  return { onChange, group: screen.getByRole('group', { name: 'Lips' }) };
}

describe('VisualFeaturePicker — lips', () => {
  it('is keyed to the lip_type spec field and uses the Interview vocabulary unchanged', () => {
    expect(LIP_CATEGORY.key).toBe('lip_type');
    expect(LIP_CATEGORY.options).toBe(LIP_TYPES);
    expect(LIP_CATEGORY.options.map((o) => o.value)).toEqual(VALUES);
    expect(LIP_CATEGORY.options.map((o) => o.label)).toEqual(LABELS);
  });

  it('renders four cards, three across, each with its human-readable label and a hint', () => {
    const { group } = renderLips();
    expect(group.className).toContain('grid-cols-3');
    const buttons = within(group).getAllByRole('button');
    expect(buttons).toHaveLength(4);
    expect(buttons.map((b) => b.textContent)).toEqual(LABELS.map((l) => expect.stringContaining(l)));
    for (const b of buttons) expect(b.getAttribute('aria-pressed')).toBe('false');
    expect(within(group).getByText('Peaked top lip')).toBeTruthy(); // cupid_bow
  });

  it('writes the exact stored DNA value for every card — cupid_bow keeps its underscore', () => {
    const { onChange, group } = renderLips();
    VALUES.forEach((value, i) => {
      fireEvent.click(within(group).getByRole('button', { name: new RegExp(LABELS[i]) }));
      expect(onChange).toHaveBeenLastCalledWith(value);
    });
    expect(onChange).toHaveBeenCalledTimes(4);
  });

  it('shows an already-stored value as the pressed card (resume / edit)', () => {
    const { group } = renderLips('cupid_bow');
    const cupid = within(group).getByRole('button', { name: /Cupid bow/ });
    expect(cupid.getAttribute('aria-pressed')).toBe('true');
    expect(cupid.querySelector('svg')).toBeTruthy(); // tick badge
    expect(cupid.className).toContain('border-gem');
    const others = within(group).getAllByRole('button').filter((b) => b !== cupid);
    expect(others).toHaveLength(3);
    for (const b of others) expect(b.getAttribute('aria-pressed')).toBe('false');
  });

  it('clears on re-press of the active card and switches on press of another — the shared picker semantics', () => {
    const { onChange, group } = renderLips('full');
    fireEvent.click(within(group).getByRole('button', { name: /Full/ }));
    expect(onChange).toHaveBeenLastCalledWith(undefined);
    fireEvent.click(within(group).getByRole('button', { name: /Thin/ }));
    expect(onChange).toHaveBeenLastCalledWith('thin');
  });

  it('points every card at the feminine and masculine asset paths', () => {
    for (const set of ['feminine', 'masculine'] as const) {
      const { group } = renderLips(undefined, set);
      const srcs = [...group.querySelectorAll('img')].map((i) => i.getAttribute('src'));
      expect(srcs).toEqual(VALUES.map((v) => `/creator-refs/lip_type/${set}/${v}.webp`));
      expect(srcs).toEqual(VALUES.map((v) => refAssetUrl('lip_type', set, v)));
      cleanup();
    }
  });

  it('degrades to the neutral tile with the label intact when an image is missing', () => {
    const { group } = renderLips();
    const balanced = within(group).getByRole('button', { name: /Balanced/ });
    fireEvent.error(balanced.querySelector('img') as HTMLImageElement);
    expect(balanced.querySelector('img')).toBeNull();
    expect(within(balanced).getByTestId('ref-placeholder')).toBeTruthy();
    expect(within(balanced).getByText('Balanced')).toBeTruthy();
  });
});
