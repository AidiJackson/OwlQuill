// @vitest-environment jsdom
/**
 * The WriteSpace finalisation record: navigation state, validated on read,
 * addressed to exactly one destination, and never evidence of anything.
 */
import { beforeEach, describe, expect, it } from 'vitest';
import {
  clearFinalisation,
  clearWriteSpaceDraft,
  readFinalisation,
  writeFinalisation,
  WRITESPACE_BODY_KEY,
  WRITESPACE_SESSION_KEY,
  WRITESPACE_TITLE_KEY,
} from '../writespaceFinalise';

const KEY = 'ficshon.writespace.finalise';
const NOW = Date.parse('2026-09-29T12:00:00Z');
const base = {
  sessionId: 'sess-1',
  characterId: 42,
  contentType: 'ic' as const,
  title: 'Lanterns',
  body: 'Pan crossed the harbour.',
  realmId: null,
};

beforeEach(() => {
  sessionStorage.clear();
  localStorage.clear();
});

describe('writeFinalisation / readFinalisation', () => {
  it('round-trips a Commons record under its own key', () => {
    expect(writeFinalisation(base, NOW)).toBe(true);
    expect(readFinalisation({ commons: true }, NOW)).toEqual({ ...base, v: 1, createdAt: NOW });
    expect(sessionStorage.getItem('ficshon.composition.handoff')).toBeNull();
  });

  it('is addressed to one destination only', () => {
    writeFinalisation({ ...base, realmId: 9 }, NOW);
    expect(readFinalisation({ realmId: 9 }, NOW)).not.toBeNull();
    expect(readFinalisation({ realmId: 10 }, NOW)).toBeNull();
    expect(readFinalisation({ commons: true }, NOW)).toBeNull();
    // Left for its own composer.
    expect(sessionStorage.getItem(KEY)).not.toBeNull();
  });

  it('reading does not consume, so a reload restores it', () => {
    writeFinalisation(base, NOW);
    readFinalisation({ commons: true }, NOW);
    expect(readFinalisation({ commons: true }, NOW)).not.toBeNull();
  });

  it.each([
    ['malformed JSON', '{nope'],
    ['a future version', JSON.stringify({ ...base, v: 2, createdAt: NOW })],
    ['no character', JSON.stringify({ ...base, v: 1, characterId: 0, createdAt: NOW })],
    ['an unknown voice', JSON.stringify({ ...base, v: 1, contentType: 'shout', createdAt: NOW })],
    ['an empty body', JSON.stringify({ ...base, v: 1, body: '  ', createdAt: NOW })],
    ['an oversized session id', JSON.stringify({ ...base, v: 1, sessionId: 'x'.repeat(37), createdAt: NOW })],
    ['a realm that is not an id', JSON.stringify({ ...base, v: 1, realmId: 'harbour', createdAt: NOW })],
    ['an expired record', JSON.stringify({ ...base, v: 1, createdAt: NOW - 25 * 3600_000 })],
  ])('rejects and removes %s', (_label, raw) => {
    sessionStorage.setItem(KEY, raw);
    expect(readFinalisation({ commons: true }, NOW)).toBeNull();
    expect(sessionStorage.getItem(KEY)).toBeNull();
  });

  it('accepts a record with no session — it simply carries no evidence', () => {
    writeFinalisation({ ...base, sessionId: null }, NOW);
    expect(readFinalisation({ commons: true }, NOW)?.sessionId).toBeNull();
  });

  it('clearFinalisation removes it', () => {
    writeFinalisation(base, NOW);
    clearFinalisation();
    expect(sessionStorage.getItem(KEY)).toBeNull();
  });
});

describe('clearWriteSpaceDraft', () => {
  it('removes the draft, title and session id and nothing else', () => {
    localStorage.setItem(WRITESPACE_BODY_KEY, 'b');
    localStorage.setItem(WRITESPACE_TITLE_KEY, 't');
    localStorage.setItem(WRITESPACE_SESSION_KEY, 's');
    localStorage.setItem('ficshon.writespace.selected_character_id', '42');
    clearWriteSpaceDraft();
    expect(localStorage.getItem(WRITESPACE_BODY_KEY)).toBeNull();
    expect(localStorage.getItem(WRITESPACE_TITLE_KEY)).toBeNull();
    expect(localStorage.getItem(WRITESPACE_SESSION_KEY)).toBeNull();
    expect(localStorage.getItem('ficshon.writespace.selected_character_id')).toBe('42');
  });

  it('uses the keys WriteSpace has always autosaved to', () => {
    expect(WRITESPACE_BODY_KEY).toBe('ficshon.workspace.body');
    expect(WRITESPACE_TITLE_KEY).toBe('ficshon.workspace.title');
    expect(WRITESPACE_SESSION_KEY).toBe('ficshon.writespace.composition_session_id');
  });
});
