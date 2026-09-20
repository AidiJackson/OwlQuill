// @vitest-environment jsdom
/**
 * Polish Phase 6.3 — an image's stored kind never reaches an ordinary
 * surface as a raw enum.
 *
 * `scene_only` is what the database says; "Scene" is what a creator reads.
 * The Image Library already went through GALLERY_KIND_LABELS; the gallery
 * card, the lightbox and the avatar/cover picker formatted the enum by hand
 * and showed "scene only". One helper, `imageKindLabel`, is now the only
 * road from a kind to a label — these tests pin the helper, the card, and
 * that filtering still runs on the canonical values.
 */
import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import {
  GALLERY_KINDS,
  GALLERY_KIND_LABELS,
  imageKindLabel,
  isGalleryKind,
} from '../galleryKinds';
import ImageCard from '../components/ImageCard';
import imageCardSource from '../components/ImageCard.tsx?raw';
import pickerSource from '../components/CharacterImagePicker.tsx?raw';
import characterDetailSource from '../../../pages/CharacterDetail.tsx?raw';
import imagesSource from '../../../pages/Images.tsx?raw';
import type { CharacterGalleryImage } from '@/lib/types';

afterEach(cleanup);

describe('imageKindLabel', () => {
  it('presents scene_only as "Scene"', () => {
    expect(imageKindLabel('scene_only')).toBe('Scene');
  });

  it('uses the product label for every gallery kind', () => {
    for (const kind of GALLERY_KINDS) {
      expect(imageKindLabel(kind)).toBe(GALLERY_KIND_LABELS[kind]);
    }
    expect(imageKindLabel('generated')).toBe('Generated');
    expect(imageKindLabel('cover')).toBe('Cover');
  });

  it('never returns an underscore for any kind', () => {
    for (const kind of [
      ...GALLERY_KINDS,
      'uploaded',
      'identity_face_ref',
      'anchor_front',
      'anchor_three_quarter',
      'identity_final_character_card',
      'some_future_kind',
    ]) {
      expect(imageKindLabel(kind)).not.toMatch(/_/);
    }
  });

  it('gives an unknown or future kind a readable fallback instead of the enum', () => {
    expect(imageKindLabel('identity_face_ref')).toBe('Identity face ref');
    expect(imageKindLabel('some_future_kind')).toBe('Some future kind');
    expect(imageKindLabel('uploaded')).toBe('Uploaded');
  });

  it('does not crash on a missing kind', () => {
    expect(imageKindLabel(undefined)).toBe('Image');
    expect(imageKindLabel(null)).toBe('Image');
    expect(imageKindLabel('')).toBe('Image');
    expect(imageKindLabel('___')).toBe('Image');
  });

  it('is presentation only — filtering still runs on the canonical enum values', () => {
    // The label must not become a second identity for the kind: "Scene" is
    // not a gallery kind, `scene_only` is. Anything that compares against the
    // label instead of the value would silently empty a gallery.
    expect(isGalleryKind('scene_only')).toBe(true);
    expect(isGalleryKind('Scene')).toBe(false);
    expect([...GALLERY_KINDS]).toEqual(['generated', 'cover', 'scene_only']);
  });
});

describe('ImageCard', () => {
  const img = (kind: string): CharacterGalleryImage => ({
    id: 1, character_id: 42, kind, url: '/one.png', created_at: '2026-09-01T00:00:00Z',
  });

  it('describes a scene_only image as "Scene", never "scene only"', () => {
    render(<ImageCard image={img('scene_only')} />);
    expect(screen.getByRole('img', { name: 'Scene' })).toBeTruthy();
    expect(screen.queryByRole('img', { name: /scene only/i })).toBeNull();
    expect(screen.queryByRole('img', { name: /scene_only/ })).toBeNull();
  });

  it('gives every gallery kind its product label as alt text', () => {
    for (const kind of GALLERY_KINDS) {
      const { unmount } = render(<ImageCard image={img(kind)} />);
      expect(screen.getByRole('img', { name: GALLERY_KIND_LABELS[kind] })).toBeTruthy();
      unmount();
    }
  });

  it('renders a working reference an owner can see with a readable alt, not the enum', () => {
    render(<ImageCard image={img('identity_face_ref')} />);
    expect(screen.getByRole('img', { name: 'Identity face ref' })).toBeTruthy();
  });
});

describe('ordinary surfaces format kinds through one source (source-level pin)', () => {
  it.each([
    ['ImageCard', imageCardSource],
    ['CharacterImagePicker', pickerSource],
    ['CharacterDetail', characterDetailSource],
    ['Images', imagesSource],
  ])('%s does not hand-format image.kind', (_name, source) => {
    expect(source).not.toMatch(/kind\)?\s*\?*\.replace\(\/_\/g/);
    expect(source).toMatch(/imageKindLabel/);
  });
});
