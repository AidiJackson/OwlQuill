/**
 * CharacterEditDetails — owner editing of a character's ORDINARY profile
 * fields and its visibility (Polish Phase 5.4, PD-1 / PD-2).
 *
 * Lives inside the Manage tab of CharacterDetail. It is management of the
 * profile that already exists, not a return to character creation: nothing
 * here touches identity — no species, age, gender, personality, DNA, canon
 * or geometry — and saving regenerates nothing and calls no image provider.
 * It sends one PATCH with only the fields that changed.
 *
 * What is editable is exactly PD-1: name, alias, role, era, short bio, long
 * bio, tags. Visibility offers exactly PD-2: Public or Private. "friends"
 * remains a value the server accepts and treats as private on every read;
 * it is not offered, and a character still carrying it is shown as such
 * until the owner picks one of the two.
 *
 * Ownership is the caller's business: the parent renders this only for
 * `character.is_owner`. The PATCH is the real boundary; this is an affordance.
 */
import { useEffect, useId, useState } from 'react';
import { Pencil, Loader2, Globe, Lock } from 'lucide-react';
import { apiClient } from '@/lib/apiClient';
import type { Character, CharacterProfilePatch } from '@/lib/types';

// ── Field contract (mirrors the server, never contradicts it) ──────────
//
// Server: name 1–100 chars, required; every other field optional and
// nullable; tags an opaque comma-separated string. Name and alias are
// normalised and policed on the server (services/character_names: NFC,
// whitespace, invisible/control characters, links, reserved names, and —
// during the closed beta — case-insensitive name uniqueness); its refusal
// arrives as one sentence in `detail` and is shown verbatim below. The other
// fields are not trimmed on the server, so trimming happens here. An optional
// field the owner empties is sent as null (which clears it) rather than ""
// (which would store "").

export const NAME_MAX = 100;

export type EditableVisibility = 'public' | 'private';

const TEXT_FIELDS = ['alias', 'role', 'era', 'short_bio', 'long_bio'] as const;

interface Draft {
  name: string;
  alias: string;
  role: string;
  era: string;
  short_bio: string;
  long_bio: string;
  tags: string;
  visibility: Character['visibility'];
}

/** "a ,b,, c " → "a, b, c"; nothing left → "". Never invents empty tags. */
export function normaliseTags(raw: string): string {
  return raw
    .split(',')
    .map((t) => t.trim())
    .filter(Boolean)
    .join(', ');
}

function draftFrom(c: Character): Draft {
  return {
    name: c.name ?? '',
    alias: c.alias ?? '',
    role: c.role ?? '',
    era: c.era ?? '',
    short_bio: c.short_bio ?? '',
    long_bio: c.long_bio ?? '',
    tags: c.tags ?? '',
    visibility: c.visibility,
  };
}

/** The PATCH body: only what differs from the character as it stands. */
export function buildPatch(character: Character, draft: Draft): CharacterProfilePatch {
  const patch: CharacterProfilePatch = {};
  const name = draft.name.trim();
  if (name !== character.name) patch.name = name;
  for (const field of TEXT_FIELDS) {
    const next = draft[field].trim();
    const current = character[field] ?? '';
    if (next !== current) patch[field] = next === '' ? null : next;
  }
  const tags = normaliseTags(draft.tags);
  if (tags !== (character.tags ?? '')) patch.tags = tags === '' ? null : tags;
  if (draft.visibility !== character.visibility) patch.visibility = draft.visibility;
  return patch;
}

function validateName(name: string): string | null {
  const trimmed = name.trim();
  if (!trimmed) return 'Your character needs a name.';
  if (trimmed.length > NAME_MAX) return `Names are at most ${NAME_MAX} characters.`;
  return null;
}

// ── Visibility copy: describes verified server behaviour only ──────────
//
// PUBLIC: the detail read, directory/search and @-mention resolution admit
// the character; a Character Home additionally needs the founder flag.
// PRIVATE: the detail read answers 404 to anyone but the owner; search,
// the directory and mentions exclude it. Nothing about already-published
// posts/comments changes — feeds do not filter on character visibility.

const VISIBILITY_OPTIONS: {
  value: EditableVisibility;
  label: string;
  description: string;
  Icon: typeof Globe;
}[] = [
  {
    value: 'public',
    label: 'Public',
    description: 'Your character can appear in Ficshon discovery and other people can view their profile.',
    Icon: Globe,
  },
  {
    value: 'private',
    label: 'Private',
    description: "Only you can open this character's profile. They are hidden from discovery.",
    Icon: Lock,
  },
];

export const PRIVATE_NOTE =
  'Making a character private does not remove posts or comments they already shared in public or shared spaces.';

function visibilityLabel(v: Character['visibility']): string {
  if (v === 'public') return 'Public';
  if (v === 'private') return 'Private';
  return 'Private (legacy setting)';
}

// ── Component ───────────────────────────────────────────────────────────

interface Props {
  character: Character;
  /** Called with the server's response — the canonical updated character. */
  onSaved: (updated: Character) => void;
}

export default function CharacterEditDetails({ character, onSaved }: Props) {
  const uid = useId();
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<Draft>(() => draftFrom(character));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [nameError, setNameError] = useState<string | null>(null);
  const [savedFlash, setSavedFlash] = useState(false);

  // A fresh character (navigation, or a save elsewhere on the page) resets a
  // form that is not open. An open form keeps the owner's typing.
  useEffect(() => {
    if (!editing) setDraft(draftFrom(character));
  }, [character, editing]);

  const open = () => {
    setDraft(draftFrom(character));
    setError('');
    setNameError(null);
    setSavedFlash(false);
    setEditing(true);
  };

  const cancel = () => {
    if (saving) return;
    setDraft(draftFrom(character));
    setError('');
    setNameError(null);
    setEditing(false);
  };

  const set = (field: keyof Draft, value: string) => {
    setDraft((d) => ({ ...d, [field]: value }));
    if (field === 'name') setNameError(null);
  };

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (saving) return;
    const problem = validateName(draft.name);
    if (problem) {
      setNameError(problem);
      return;
    }
    const patch = buildPatch(character, draft);
    if (Object.keys(patch).length === 0) {
      setEditing(false);
      return;
    }
    setSaving(true);
    setError('');
    try {
      const updated = await apiClient.updateCharacter(character.id, patch);
      onSaved(updated);
      setEditing(false);
      setSavedFlash(true);
      setTimeout(() => setSavedFlash(false), 2500);
    } catch (err) {
      // The server's own message: it is the authority on what was refused.
      setError(err instanceof Error ? err.message : 'Could not save these details.');
    } finally {
      setSaving(false);
    }
  };

  const tagsPreview = normaliseTags(draft.tags);
  const legacyVisibility = draft.visibility !== 'public' && draft.visibility !== 'private';

  // ── Read view ─────────────────────────────────────────────────────
  if (!editing) {
    const summary = [character.alias, character.role, character.era].filter(Boolean).join(' · ');
    return (
      <section
        aria-labelledby={`${uid}-details-heading`}
        className="rounded-2xl p-5 bg-surface border border-edge space-y-3"
      >
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <h3 id={`${uid}-details-heading`} className="font-mono text-[11px] uppercase tracking-[0.1em] text-ink-3">
              Details
            </h3>
            <p className="text-sm text-ink mt-1 break-words">
              <span className="font-semibold">{character.name}</span>
              {summary && <span className="text-ink-2"> — {summary}</span>}
            </p>
            <p className="text-xs text-ink-3 mt-1 flex items-center gap-1.5">
              {character.visibility === 'public' ? <Globe className="w-3 h-3" aria-hidden /> : <Lock className="w-3 h-3" aria-hidden />}
              <span data-testid="visibility-state">{visibilityLabel(character.visibility)}</span>
              {savedFlash && <span className="text-gem" role="status">Saved.</span>}
            </p>
          </div>
          <button type="button" onClick={open} className="btn btn-secondary text-sm flex items-center gap-2 flex-shrink-0">
            <Pencil className="w-3.5 h-3.5" aria-hidden />
            Edit details
          </button>
        </div>
      </section>
    );
  }

  // ── Edit view ─────────────────────────────────────────────────────
  const id = (f: string) => `${uid}-${f}`;
  const fieldClass = 'input text-sm py-1.5';

  return (
    <section
      aria-labelledby={`${uid}-details-heading`}
      className="rounded-2xl p-5 bg-surface border border-edge"
    >
      <form onSubmit={submit} noValidate className="space-y-5" aria-busy={saving}>
        <div>
          <h3 id={`${uid}-details-heading`} className="font-mono text-[11px] uppercase tracking-[0.1em] text-ink-3">
            Edit details
          </h3>
          <p className="text-xs text-ink-3 mt-1">
            Profile details only. Identity, canon and images are managed separately.
          </p>
        </div>

        <fieldset disabled={saving} className="space-y-4 min-w-0">
          <legend className="sr-only">Profile</legend>

          <div>
            <label htmlFor={id('name')} className="block text-xs font-medium text-ink-2 mb-1">
              Name <span className="text-red-400" aria-hidden>*</span>
            </label>
            <input
              id={id('name')}
              className={fieldClass}
              value={draft.name}
              onChange={(e) => set('name', e.target.value)}
              maxLength={NAME_MAX}
              required
              aria-required="true"
              aria-invalid={nameError ? 'true' : undefined}
              aria-describedby={nameError ? id('name-error') : undefined}
              autoComplete="off"
            />
            {nameError && (
              <p id={id('name-error')} className="text-xs text-red-400 mt-1" role="alert">
                {nameError}
              </p>
            )}
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
            <div className="min-w-0">
              <label htmlFor={id('alias')} className="block text-xs font-medium text-ink-2 mb-1">Alias</label>
              <input id={id('alias')} className={fieldClass} value={draft.alias} onChange={(e) => set('alias', e.target.value)} autoComplete="off" />
            </div>
            <div className="min-w-0">
              <label htmlFor={id('role')} className="block text-xs font-medium text-ink-2 mb-1">Role</label>
              <input id={id('role')} className={fieldClass} value={draft.role} onChange={(e) => set('role', e.target.value)} placeholder="e.g. detective" autoComplete="off" />
            </div>
            <div className="min-w-0">
              <label htmlFor={id('era')} className="block text-xs font-medium text-ink-2 mb-1">Era</label>
              <input id={id('era')} className={fieldClass} value={draft.era} onChange={(e) => set('era', e.target.value)} placeholder="e.g. 1920s" autoComplete="off" />
            </div>
          </div>

          <div>
            <label htmlFor={id('short_bio')} className="block text-xs font-medium text-ink-2 mb-1">Short bio</label>
            <textarea id={id('short_bio')} className="textarea text-sm min-h-[64px]" rows={2} value={draft.short_bio} onChange={(e) => set('short_bio', e.target.value)} />
          </div>

          <div>
            <label htmlFor={id('long_bio')} className="block text-xs font-medium text-ink-2 mb-1">Long bio</label>
            <textarea id={id('long_bio')} className="textarea text-sm" rows={5} value={draft.long_bio} onChange={(e) => set('long_bio', e.target.value)} />
          </div>

          <div>
            <label htmlFor={id('tags')} className="block text-xs font-medium text-ink-2 mb-1">Tags</label>
            <input
              id={id('tags')}
              className={fieldClass}
              value={draft.tags}
              onChange={(e) => set('tags', e.target.value)}
              placeholder="e.g. noir, detective, 1920s"
              aria-describedby={id('tags-help')}
              autoComplete="off"
            />
            <p id={id('tags-help')} className="text-xs text-ink-3 mt-1">Separate tags with commas.</p>
            {tagsPreview && (
              <ul className="mt-2 flex flex-wrap gap-1.5" aria-label="Tags as they will be saved">
                {tagsPreview.split(', ').map((t) => (
                  <li key={t} className="px-2 py-0.5 bg-gem-soft text-gem text-xs rounded">{t}</li>
                ))}
              </ul>
            )}
          </div>
        </fieldset>

        <fieldset disabled={saving} className="space-y-2 min-w-0">
          <legend className="text-xs font-medium text-ink-2 mb-1">Visibility</legend>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2" role="radiogroup" aria-label="Visibility">
            {VISIBILITY_OPTIONS.map(({ value, label, description, Icon }) => {
              const checked = draft.visibility === value;
              return (
                <label
                  key={value}
                  htmlFor={id(`vis-${value}`)}
                  className={`flex gap-3 items-start p-3 rounded-xl border cursor-pointer transition-colors has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-gem/50 ${
                    checked ? 'border-gem/60 bg-gem-soft' : 'border-edge-md bg-surface-elevated hover:border-gem/30'
                  }`}
                >
                  <input
                    id={id(`vis-${value}`)}
                    type="radio"
                    name={`${uid}-visibility`}
                    value={value}
                    checked={checked}
                    onChange={() => set('visibility', value)}
                    aria-labelledby={id(`vis-${value}-label`)}
                    aria-describedby={id(`vis-${value}-desc`)}
                    className="mt-0.5 accent-[rgb(var(--gem))]"
                  />
                  <span className="min-w-0">
                    <span id={id(`vis-${value}-label`)} className="flex items-center gap-1.5 text-sm font-medium text-ink">
                      <Icon className="w-3.5 h-3.5" aria-hidden />
                      {label}
                    </span>
                    <span id={id(`vis-${value}-desc`)} className="block text-xs text-ink-3 mt-0.5">{description}</span>
                  </span>
                </label>
              );
            })}
          </div>
          {legacyVisibility && (
            <p className="text-xs text-amber-400">
              This character is on an older setting that works like Private. Choose Public or Private to update it.
            </p>
          )}
          {draft.visibility === 'private' && (
            <p className="text-xs text-ink-3" data-testid="private-note">{PRIVATE_NOTE}</p>
          )}
        </fieldset>

        {error && (
          <p className="text-sm text-red-400" role="alert">{error}</p>
        )}

        <div className="flex flex-wrap items-center gap-2">
          <button type="submit" disabled={saving} className="btn btn-primary text-sm flex items-center gap-2">
            {saving && <Loader2 className="w-3.5 h-3.5 animate-spin" aria-hidden />}
            {saving ? 'Saving…' : 'Save changes'}
          </button>
          <button type="button" onClick={cancel} disabled={saving} className="btn btn-secondary text-sm">
            Cancel
          </button>
        </div>
      </form>
    </section>
  );
}
