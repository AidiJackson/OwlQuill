// @vitest-environment jsdom
//
// The Interview shell and its groups, as a user sees them (Polish Phase 1).
import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';

import StepPersonality from '../StepPersonality';
import type { CreationBasics, CreationSeeds } from '../../shared/types';

afterEach(cleanup);

function setup(seeds: Partial<CreationSeeds> = {}, basics: Partial<CreationBasics> = {}) {
  const onChange = vi.fn();
  const onBasicsChange = vi.fn();
  const onNext = vi.fn();
  const view = render(
    <StepPersonality
      basics={{ name: '', alias: '', ...basics }}
      onBasicsChange={onBasicsChange}
      data={{ traits: [], identitySpec: null, ...seeds }}
      onChange={onChange}
      onNext={onNext}
      saving={false}
    />,
  );
  return { ...view, onChange, onBasicsChange, onNext };
}

const next = () => fireEvent.click(screen.getByRole('button', { name: /^Next/ }));
const chip = (group: string, label: string) =>
  within(screen.getByRole('group', { name: group })).getByRole('button', { name: label });

describe('Interview — progress and navigation (C11)', () => {
  it('shows six groups with a count and real Next/Back buttons', () => {
    setup();
    expect(screen.getByText('1 of 6 · Basics')).toBeTruthy();
    expect(screen.getByRole('button', { name: /^Back/ })).toHaveProperty('disabled', true);
    next();
    expect(screen.getByText('2 of 6 · Face')).toBeTruthy();
    expect(screen.getByRole('button', { name: /^Back/ })).toHaveProperty('disabled', false);
    next(); next(); next(); next();
    expect(screen.getByText('6 of 6 · Character')).toBeTruthy();
    expect(screen.queryByRole('button', { name: /^Next/ })).toBeNull();
    expect(screen.getByText('Last question')).toBeTruthy();
  });

  it('marks name, gender and age range as required before the user is ever told', () => {
    setup();
    const required = screen.getAllByText('Required');
    expect(required).toHaveLength(3);
  });

  it('refuses to continue without the required answers and returns to the first group', () => {
    const { onNext } = setup();
    next(); next();
    fireEvent.click(screen.getByRole('button', { name: 'Continue to Sketch' }));
    expect(onNext).not.toHaveBeenCalled();
    expect(screen.getByText('1 of 6 · Basics')).toBeTruthy();
    expect(screen.getByRole('alert').textContent).toMatch(/Name, gender and age range/);
    expect(screen.getByText('A name is needed.')).toBeTruthy();
  });

  it('continues once name, gender and age range are answered', () => {
    const { onNext } = setup(
      { identitySpec: { gender: 'female', age_band: '26-35' } as never },
      { name: 'Bertie' },
    );
    fireEvent.click(screen.getByRole('button', { name: 'Continue to Sketch' }));
    expect(onNext).toHaveBeenCalledTimes(1);
  });
});

describe('Interview — vocabulary (C4, C5, C8)', () => {
  it('asks name, alias, gender, age and species in the opening group and nowhere else', () => {
    setup();
    expect(screen.getByLabelText('Character name')).toBeTruthy();
    expect(screen.getByLabelText('Character alias')).toBeTruthy();
    expect(screen.getByRole('group', { name: 'Gender' })).toBeTruthy();
    expect(screen.getByRole('group', { name: 'Age range' })).toBeTruthy();
    expect(screen.getByRole('group', { name: 'Species' })).toBeTruthy();
    for (let i = 0; i < 5; i += 1) {
      next();
      expect(screen.queryByRole('group', { name: 'Gender' })).toBeNull();
      expect(screen.queryByRole('group', { name: 'Species' })).toBeNull();
    }
  });

  it('no longer offers Style, Marks & accessories, Artist notes or Brows (detailed)', () => {
    setup();
    for (let i = 0; i < 6; i += 1) {
      expect(screen.queryByText(/^Style$/)).toBeNull();
      expect(screen.queryByText(/Marks and accessories/i)).toBeNull();
      expect(screen.queryByText(/Artist notes/i)).toBeNull();
      expect(screen.queryByText(/Brows \(detailed\)/i)).toBeNull();
      expect(screen.queryByRole('combobox')).toBeNull();
      if (i < 5) next();
    }
  });

  it('labels the hairline option "Uneven" while storing "messy" (C9)', () => {
    const { onChange } = setup({ identitySpec: { gender: 'male', age_band: '36-50' } as never });
    next(); next(); next(); next();
    fireEvent.click(chip('Hairline', 'Uneven'));
    expect(onChange).toHaveBeenLastCalledWith(
      expect.objectContaining({ identitySpec: expect.objectContaining({ hairline_type: 'messy' }) }),
    );
  });

  it('explains what personality traits do', () => {
    setup();
    next(); next(); next(); next(); next();
    expect(screen.getByText(/overall feel of your character/i)).toBeTruthy();
    expect(screen.getByRole('group', { name: 'Personality traits' })).toBeTruthy();
  });
});

describe('Interview — hair rule (C9)', () => {
  it('choosing Shaved hides texture and style and clears their stored values', () => {
    const { onChange } = setup({
      identitySpec: {
        gender: 'female', age_band: '18-25', species: 'human', species_tells: [],
        identity: { hair_color: 'Black', hair_length: 'Long', eye_color: '', skin_tone: '', face_features: [] },
        hair_style: 'slicked_back', hair_texture: 'wavy',
      } as never,
    });
    next(); next(); next(); next();
    expect(screen.getByRole('group', { name: 'Hair texture' })).toBeTruthy();
    expect(screen.getByRole('group', { name: 'Hair style' })).toBeTruthy();

    fireEvent.click(chip('Hair length', 'Shaved'));

    expect(screen.queryByRole('group', { name: 'Hair texture' })).toBeNull();
    expect(screen.queryByRole('group', { name: 'Hair style' })).toBeNull();
    const sent = onChange.mock.calls[onChange.mock.calls.length - 1][0].identitySpec;
    expect(sent.identity.hair_length).toBe('Shaved');
    expect(sent.hair_style).toBeUndefined();
    expect(sent.hair_texture).toBeUndefined();
  });
});
