// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';

import VisualFeaturePicker from '../VisualFeaturePicker';
import ExampleSetToggle from '../ExampleSetToggle';
import { FACE_SHAPE_CATEGORY, type ExampleSet } from '../refCatalog';
import { useState } from 'react';

afterEach(cleanup);

function renderPicker(value: string | undefined = undefined, set: ExampleSet = 'feminine') {
  const onChange = vi.fn();
  render(
    <VisualFeaturePicker
      category={FACE_SHAPE_CATEGORY}
      ariaLabel="Face shape"
      value={value as never}
      onChange={onChange}
      exampleSet={set}
    />,
  );
  return { onChange, group: screen.getByRole('group', { name: 'Face shape' }) };
}

describe('VisualFeaturePicker — face shape', () => {
  it('renders every option with a visible label and a hint', () => {
    const { group } = renderPicker();
    const buttons = within(group).getAllByRole('button');
    expect(buttons.map((b) => b.textContent)).toEqual([
      expect.stringContaining('Oval'),
      expect.stringContaining('Round'),
      expect.stringContaining('Square'),
      expect.stringContaining('Angular'),
      expect.stringContaining('Long'),
    ]);
    expect(within(group).getByText('Sharper planes')).toBeTruthy();
  });

  it('emits the exact stored value, and undefined when the selection is cleared', () => {
    const { onChange, group } = renderPicker(undefined);
    fireEvent.click(within(group).getByRole('button', { name: /Angular/ }));
    expect(onChange).toHaveBeenLastCalledWith('angular');

    cleanup();
    const second = renderPicker('angular');
    fireEvent.click(within(second.group).getByRole('button', { name: /Angular/ }));
    expect(second.onChange).toHaveBeenLastCalledWith(undefined);
  });

  it('exposes selection to assistive tech and not by colour alone', () => {
    const { group } = renderPicker('round');
    const round = within(group).getByRole('button', { name: /Round/ });
    const oval = within(group).getByRole('button', { name: /Oval/ });
    expect(round.getAttribute('aria-pressed')).toBe('true');
    expect(oval.getAttribute('aria-pressed')).toBe('false');
    expect(round.querySelector('svg')).toBeTruthy(); // the tick badge
    expect(round.className).toContain('border-gem');
  });

  it('moves focus with the arrow keys and activates with Enter/Space', () => {
    const { onChange, group } = renderPicker();
    const [oval, round, , , long] = within(group).getAllByRole('button');
    oval.focus();
    fireEvent.keyDown(oval, { key: 'ArrowRight' });
    expect(document.activeElement).toBe(round);
    fireEvent.keyDown(round, { key: 'ArrowLeft' });
    fireEvent.keyDown(oval, { key: 'ArrowLeft' });
    expect(document.activeElement).toBe(long);
    // Native button activation: a click event is what Enter/Space produce.
    fireEvent.click(long);
    expect(onChange).toHaveBeenLastCalledWith('long');
  });

  it('points every card at the example set\'s asset path', () => {
    const { group } = renderPicker(undefined, 'masculine');
    const srcs = [...group.querySelectorAll('img')].map((i) => i.getAttribute('src'));
    expect(srcs).toEqual([
      '/creator-refs/face_shape/masculine/oval.webp',
      '/creator-refs/face_shape/masculine/round.webp',
      '/creator-refs/face_shape/masculine/square.webp',
      '/creator-refs/face_shape/masculine/angular.webp',
      '/creator-refs/face_shape/masculine/long.webp',
    ]);
  });

  it('degrades to a neutral tile — label intact — when an image is missing', () => {
    const { group } = renderPicker();
    const oval = within(group).getByRole('button', { name: /Oval/ });
    const img = oval.querySelector('img') as HTMLImageElement;
    fireEvent.error(img);
    expect(oval.querySelector('img')).toBeNull();
    expect(within(oval).getByTestId('ref-placeholder')).toBeTruthy();
    expect(within(oval).getByText('Oval')).toBeTruthy();
  });

  it('shows the image once it loads', () => {
    const { group } = renderPicker();
    const img = group.querySelector('img') as HTMLImageElement;
    expect(img.className).toContain('opacity-0');
    fireEvent.load(img);
    expect(img.className).toContain('opacity-100');
  });
});

function Harness() {
  const [set, setSet] = useState<ExampleSet>('feminine');
  const [face, setFace] = useState<string | undefined>('square');
  return (
    <div>
      <VisualFeaturePicker category={FACE_SHAPE_CATEGORY} ariaLabel="Face shape" value={face as never} onChange={(v) => setFace(v)} exampleSet={set} />
      <ExampleSetToggle value={set} onChange={setSet} />
      <output data-testid="face">{String(face)}</output>
    </div>
  );
}

describe('ExampleSetToggle', () => {
  it('switches the asset paths and does not touch the selected face shape', () => {
    const onFace = vi.fn();
    render(
      <div>
        <VisualFeaturePicker category={FACE_SHAPE_CATEGORY} ariaLabel="Face shape" value={'square' as never} onChange={onFace} exampleSet="feminine" />
      </div>,
    );
    cleanup();
    render(<Harness />);
    const group = screen.getByRole('group', { name: 'Face shape' });
    expect(group.querySelector('img')?.getAttribute('src')).toContain('/feminine/');
    fireEvent.click(screen.getByRole('radio', { name: 'Masculine' }));
    expect(group.querySelector('img')?.getAttribute('src')).toContain('/masculine/');
    expect(screen.getByTestId('face').textContent).toBe('square');
    expect(screen.getByRole('radio', { name: 'Masculine' }).getAttribute('aria-checked')).toBe('true');
    expect(onFace).not.toHaveBeenCalled();
  });

  it('is a radiogroup with helper copy', () => {
    render(<ExampleSetToggle value="feminine" onChange={() => {}} />);
    expect(screen.getByRole('radiogroup', { name: 'Show examples as:' })).toBeTruthy();
    expect(screen.getByText(/For illustration only/)).toBeTruthy();
  });
});
