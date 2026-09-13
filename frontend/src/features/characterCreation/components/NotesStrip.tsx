// The artist's notes — the answered Interview values, as a quiet line of text
// under the sketch pad. Moved out of StepPersonality in Polish Phase 1 with
// no change in what it lists, other than reading the same fields the
// Interview still asks (brow_type is gone; eyebrow_shape remains).
import type { IdentitySpec } from '../shared/types';
import { GENDER_OPTIONS, SPECIES_OPTIONS } from '../shared/types';

export default function NotesStrip({ spec, width = 154 }: { spec: IdentitySpec; width?: number }) {
  const parts: string[] = [];
  if (spec.gender) parts.push(GENDER_OPTIONS.find((g) => g.value === spec.gender)?.label ?? spec.gender);
  if (spec.age_band) parts.push(spec.age_band);
  if (spec.species && spec.species !== 'human') {
    parts.push(SPECIES_OPTIONS.find((s) => s.value === spec.species)?.label ?? spec.species);
  }
  if (spec.face_shape) parts.push(spec.face_shape);
  if (spec.jaw_type) parts.push(spec.jaw_type + ' jaw');
  if (spec.eye_shape) parts.push(spec.eye_shape.replace(/_/g, ' ') + ' eyes');
  if (spec.identity?.eye_color) parts.push(spec.identity.eye_color);
  if (spec.nose_type) parts.push(spec.nose_type + ' nose');
  if (spec.lip_type) parts.push(spec.lip_type.replace(/_/g, ' ') + ' lips');
  if (spec.identity?.hair_color) parts.push(spec.identity.hair_color);
  if (spec.identity?.hair_length) parts.push(spec.identity.hair_length + ' hair');
  if (spec.hair_texture) parts.push(spec.hair_texture);
  if (spec.hair_style) parts.push(spec.hair_style.replace(/_/g, ' '));
  if (spec.eyebrow_shape) parts.push(spec.eyebrow_shape + ' brows');
  if (spec.facial_hair_type && spec.facial_hair_type !== 'none') parts.push(spec.facial_hair_type.replace(/_/g, ' '));

  if (!parts.length) return null;

  return (
    <p className="text-[10px] text-ink-3 leading-relaxed mt-2" style={{ maxWidth: width }}>
      {parts.join(' · ')}
    </p>
  );
}
