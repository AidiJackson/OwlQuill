import { describe, it, expect } from 'vitest';
import { isInsertion } from '../composition';

/**
 * The typed-vs-inserted rule. Both directions of error mislabel real writing —
 * calling a paste "typed" hands out a badge nobody earned, and calling typing
 * "pasted" takes one away from someone who did the work.
 */
describe('isInsertion', () => {
  it('treats single keystrokes as typing', () => {
    expect(isInsertion({ inputType: 'insertText', delta: 1, recentPaste: false })).toBe(false);
  });

  it('treats a two-character IME commit as typing', () => {
    expect(
      isInsertion({ inputType: 'insertCompositionText', delta: 2, recentPaste: false }),
    ).toBe(false);
  });

  it('treats an explicit paste as an insertion', () => {
    expect(isInsertion({ inputType: 'insertFromPaste', delta: 1, recentPaste: false })).toBe(true);
  });

  it('treats a drop as an insertion', () => {
    expect(isInsertion({ inputType: 'insertFromDrop', delta: 40, recentPaste: false })).toBe(true);
  });

  it('falls back to the recent-paste signal when inputType is missing', () => {
    // Browsers that fire `paste` but give no `inputType` on `beforeinput`.
    expect(isInsertion({ inputType: '', delta: 1, recentPaste: true })).toBe(true);
  });

  it('counts unattributed bulk text as an insertion', () => {
    // Autocomplete or an extension dumping a paragraph in. Without a paste
    // signal we still refuse to call it typing.
    expect(isInsertion({ inputType: 'insertText', delta: 900, recentPaste: false })).toBe(true);
  });
});
