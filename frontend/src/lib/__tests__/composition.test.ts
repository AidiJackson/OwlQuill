import { describe, it, expect } from 'vitest';
import { isInsertion, isHistoryEdit } from '../composition';

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

/**
 * Keyboard composition. The size rule alone says "more than two characters at
 * once is not typing", which on a phone is false: a swipe commits a whole word
 * and a CJK IME commits a whole phrase. Under the old rule a post swiped out on
 * a phone reported almost entirely inserted characters and published as
 * "Created elsewhere" — for being written on a touchscreen.
 */
describe('isInsertion — keyboard composition', () => {
  it('treats an Android gesture-typed word as typing', () => {
    expect(
      isInsertion({ inputType: 'insertCompositionText', delta: 7, recentPaste: false }),
    ).toBe(false);
  });

  it('treats a whole IME phrase as typing', () => {
    // A Japanese or Chinese IME commits many characters in one input event.
    expect(
      isInsertion({ inputType: 'insertCompositionText', delta: 24, recentPaste: false }),
    ).toBe(false);
  });

  it('treats input during an active composition as typing even without an inputType', () => {
    expect(
      isInsertion({ inputType: '', delta: 9, recentPaste: false, inComposition: true }),
    ).toBe(false);
  });

  it('still calls a paste a paste when a composition is active', () => {
    // Composition must not become a way to launder a paste. The explicit paste
    // signal is checked first and wins.
    expect(
      isInsertion({
        inputType: 'insertFromPaste',
        delta: 4000,
        recentPaste: false,
        inComposition: true,
      }),
    ).toBe(true);
    expect(
      isInsertion({ inputType: '', delta: 4000, recentPaste: true, inComposition: true }),
    ).toBe(true);
  });

  it('still counts a bulk insert outside a composition', () => {
    // The exemption is for composition, not for large inputs generally.
    expect(
      isInsertion({ inputType: 'insertText', delta: 4000, recentPaste: false, inComposition: false }),
    ).toBe(true);
  });

  it('counts a quoted paste as an insertion', () => {
    expect(
      isInsertion({ inputType: 'insertFromPasteAsQuotation', delta: 300, recentPaste: false }),
    ).toBe(true);
  });
});

/**
 * Undo and redo replay edits the field already counted. Counting a redo again
 * — and the size rule counted it as an *insertion* — meant typing a sentence,
 * pressing undo and pressing redo produced a post that reported itself as
 * mostly pasted.
 */
describe('isHistoryEdit', () => {
  it('recognises undo and redo', () => {
    expect(isHistoryEdit('historyUndo')).toBe(true);
    expect(isHistoryEdit('historyRedo')).toBe(true);
  });

  it('leaves ordinary input alone', () => {
    for (const kind of ['insertText', 'insertFromPaste', 'insertCompositionText', '']) {
      expect(isHistoryEdit(kind)).toBe(false);
    }
  });
});
