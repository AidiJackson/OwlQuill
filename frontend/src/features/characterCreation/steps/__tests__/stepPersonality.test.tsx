// @vitest-environment jsdom
//
// The Interview shell and its groups, as a user sees them (Polish Phase 1).
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';

import StepPersonality from '../StepPersonality';
import type { CreationBasics, CreationSeeds } from '../../shared/types';

afterEach(cleanup);
beforeEach(() => localStorage.clear());

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

describe('Interview — geometry fields as picture cards (Phase 3A face shape, 3C the rest)', () => {
  it('the six approved fields are pickers with one example-set toggle per group; everything else stays a chip row', () => {
    setup({ identitySpec: { gender: 'female', age_band: '26-35' } as never });
    next();
    const face = screen.getByRole('group', { name: 'Face shape' });
    expect(face.querySelectorAll('img').length).toBe(5);
    expect(within(face).getByRole('button', { name: /Angular/ })).toBeTruthy();
    expect(screen.getByRole('group', { name: 'Jaw' }).querySelectorAll('img').length).toBe(4);
    expect(screen.getByRole('group', { name: 'Cheekbones' }).querySelectorAll('img').length).toBe(3);
    expect(screen.getAllByRole('radiogroup')).toHaveLength(1);
    next();
    expect(screen.getByRole('group', { name: 'Eye shape' }).querySelectorAll('img').length).toBe(4);
    for (const name of ['Eye spacing', 'Eyebrows', 'Eye colour']) {
      expect(screen.getByRole('group', { name }).querySelectorAll('img').length).toBe(0);
    }
    expect(screen.getAllByRole('radiogroup')).toHaveLength(1);
    next();
    expect(screen.getByRole('group', { name: 'Nose' }).querySelectorAll('img').length).toBe(6);
    expect(screen.getByRole('group', { name: 'Lips' }).querySelectorAll('img').length).toBe(4);
    expect(screen.getAllByRole('radiogroup')).toHaveLength(1);
    next();
    expect(screen.queryByRole('radiogroup')).toBeNull();
    for (const name of ['Hair texture', 'Hair style', 'Hairline', 'Facial hair']) {
      expect(screen.getByRole('group', { name }).querySelectorAll('img').length).toBe(0);
    }
  });

  it('each 3C picker writes only its own field with the exact stored value, and clears it on re-press', () => {
    const { onChange } = setup({ identitySpec: { gender: 'female', age_band: '26-35' } as never });
    const last = () => onChange.mock.calls[onChange.mock.calls.length - 1][0].identitySpec;
    next();
    fireEvent.click(within(screen.getByRole('group', { name: 'Jaw' })).getByRole('button', { name: /Sharp/ }));
    expect(last().jaw_type).toBe('sharp');
    fireEvent.click(within(screen.getByRole('group', { name: 'Cheekbones' })).getByRole('button', { name: /High/ }));
    expect(last()).toEqual(expect.objectContaining({ jaw_type: 'sharp', cheekbone_type: 'high' }));
    next();
    fireEvent.click(within(screen.getByRole('group', { name: 'Eye shape' })).getByRole('button', { name: /Deep-set/ }));
    expect(last().eye_shape).toBe('deep_set');
    next();
    fireEvent.click(within(screen.getByRole('group', { name: 'Nose' })).getByRole('button', { name: /Upturned/ }));
    expect(last().nose_type).toBe('upturned');
    fireEvent.click(within(screen.getByRole('group', { name: 'Lips' })).getByRole('button', { name: /Cupid bow/ }));
    expect(last().lip_type).toBe('cupid_bow');
    fireEvent.click(within(screen.getByRole('group', { name: 'Lips' })).getByRole('button', { name: /Cupid bow/ }));
    expect(last().lip_type).toBeUndefined();
    expect(last()).toEqual(expect.objectContaining({ jaw_type: 'sharp', cheekbone_type: 'high', eye_shape: 'deep_set', nose_type: 'upturned' }));
  });

  it('the example-set toggle comes before the first picture field in each group', () => {
    setup({ identitySpec: { gender: 'female', age_band: '26-35' } as never });
    const toggleFirst = (group: string) => {
      const toggle = screen.getByRole('radiogroup');
      const cards = screen.getByRole('group', { name: group });
      // DOCUMENT_POSITION_FOLLOWING: the cards come after the toggle
      expect(toggle.compareDocumentPosition(cards) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    };
    next(); toggleFirst('Face shape');
    next(); toggleFirst('Eye shape');
    next(); toggleFirst('Nose');
  });

  it('the example-set choice made in one group carries to the next group', () => {
    setup({ identitySpec: { gender: 'female', age_band: '26-35' } as never });
    next();
    fireEvent.click(screen.getByRole('radio', { name: 'Masculine' }));
    next();
    expect(screen.getByRole('radio', { name: 'Masculine' }).getAttribute('aria-checked')).toBe('true');
    expect(screen.getByRole('group', { name: 'Eye shape' }).querySelector('img')?.getAttribute('src')).toBe('/creator-refs/eye_shape/masculine/almond.webp');
    next();
    expect(screen.getByRole('group', { name: 'Nose' }).querySelector('img')?.getAttribute('src')).toBe('/creator-refs/nose_type/masculine/straight.webp');
  });

  it('a picked face shape enters the spec with the same stored value as before', () => {
    const { onChange } = setup({ identitySpec: { gender: 'female', age_band: '26-35' } as never });
    next();
    fireEvent.click(within(screen.getByRole('group', { name: 'Face shape' })).getByRole('button', { name: /Angular/ }));
    expect(onChange).toHaveBeenLastCalledWith(
      expect.objectContaining({ identitySpec: expect.objectContaining({ face_shape: 'angular' }) }),
    );
    fireEvent.click(within(screen.getByRole('group', { name: 'Face shape' })).getByRole('button', { name: /Angular/ }));
    expect(onChange.mock.calls[onChange.mock.calls.length - 1][0].identitySpec.face_shape).toBeUndefined();
  });

  it('the example-set toggle defaults from gender, switches the pictures, and never touches the spec', () => {
    const { onChange } = setup({ identitySpec: { gender: 'male', age_band: '26-35', face_shape: 'square' } as never });
    next();
    const masc = screen.getByRole('radio', { name: 'Masculine' });
    expect(masc.getAttribute('aria-checked')).toBe('true');
    const face = screen.getByRole('group', { name: 'Face shape' });
    expect(face.querySelector('img')?.getAttribute('src')).toContain('/masculine/');
    fireEvent.click(screen.getByRole('radio', { name: 'Feminine' }));
    expect(face.querySelector('img')?.getAttribute('src')).toContain('/feminine/');
    expect(onChange).not.toHaveBeenCalled();
    expect(within(face).getByRole('button', { name: /Square/ }).getAttribute('aria-pressed')).toBe('true');
    expect(localStorage.getItem('ficshon.creator.exampleSet')).toBe('feminine');
  });

  it('colour chips carry a swatch and keep their exact stored values (C14)', () => {
    const { onChange } = setup({ identitySpec: { gender: 'female', age_band: '26-35' } as never });
    next(); next();
    const eye = screen.getByRole('group', { name: 'Eye colour' });
    expect(within(eye).getAllByTestId('color-swatch')).toHaveLength(7);
    fireEvent.click(chip('Eye colour', 'Hazel'));
    expect(onChange.mock.calls[onChange.mock.calls.length - 1][0].identitySpec.identity.eye_color).toBe('Hazel');
    next(); next();
    expect(within(screen.getByRole('group', { name: 'Hair colour' })).getAllByTestId('color-swatch')).toHaveLength(10);
    expect(within(screen.getByRole('group', { name: 'Skin tone' })).getAllByTestId('color-swatch')).toHaveLength(10);
    fireEvent.click(chip('Skin tone', 'Porcelain'));
    expect(onChange.mock.calls[onChange.mock.calls.length - 1][0].identitySpec.identity.skin_tone).toBe('Porcelain');
    expect(within(screen.getByRole('group', { name: 'Skin tone' })).getByText('Porcelain')).toBeTruthy();
  });
});
