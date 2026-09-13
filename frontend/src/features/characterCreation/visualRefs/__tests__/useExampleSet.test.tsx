// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { act, cleanup, renderHook } from '@testing-library/react';
import { useExampleSet } from '../useExampleSet';
import { EXAMPLE_SET_STORAGE_KEY } from '../refCatalog';

beforeEach(() => localStorage.clear());
afterEach(cleanup);

describe('useExampleSet', () => {
  it('defaults from the character gender and follows it while unchosen', () => {
    const { result, rerender } = renderHook(({ g }) => useExampleSet(g), { initialProps: { g: 'female' } });
    expect(result.current.exampleSet).toBe('feminine');
    rerender({ g: 'male' });
    expect(result.current.exampleSet).toBe('masculine');
    rerender({ g: 'other' });
    expect(result.current.exampleSet).toBe('feminine'); // documented neutral default
  });

  it('a manual choice persists and is not overridden by a later gender change', () => {
    const { result, rerender } = renderHook(({ g }) => useExampleSet(g), { initialProps: { g: 'female' } });
    act(() => result.current.setExampleSet('masculine'));
    expect(result.current.exampleSet).toBe('masculine');
    rerender({ g: 'female' });
    expect(result.current.exampleSet).toBe('masculine');
    expect(localStorage.getItem(EXAMPLE_SET_STORAGE_KEY)).toBe('masculine');
  });

  it('reads a previously stored choice on mount', () => {
    localStorage.setItem(EXAMPLE_SET_STORAGE_KEY, 'masculine');
    const { result } = renderHook(() => useExampleSet('female'));
    expect(result.current.exampleSet).toBe('masculine');
  });

  it('ignores a corrupt stored value', () => {
    localStorage.setItem(EXAMPLE_SET_STORAGE_KEY, 'neutral');
    const { result } = renderHook(() => useExampleSet('male'));
    expect(result.current.exampleSet).toBe('masculine');
  });
});
