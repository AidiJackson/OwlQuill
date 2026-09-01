// Who may use Admin Creator.
//
// An experimental founder/seeding workflow, kept deliberately separate from the
// Image Generator on /images while we learn which approach works better. It is
// NOT a user-facing feature and must not become one by accident: ordinary
// creators and Wanderers can neither see the entry point nor open the route.
//
// This is a thin alias over the existing founder entitlement rather than a new
// mechanism — admin OR seeder, exactly as the founder tools in the Image
// Generator already resolve it. Naming it separately means that if Admin
// Creator is ever opened to a premium tier, the change happens HERE and cannot
// silently widen who counts as a founder everywhere else.
//
// The client gate decides what is OFFERED. The server independently authorises
// every upload, reference and generation, and refuses a non-founder regardless
// of what the client renders.
import { isFounder } from '@/lib/entitlements';
import type { User } from '@/lib/types';

type MaybeUser = User | null | undefined;

export function canUseAdminCreator(user: MaybeUser): boolean {
  return isFounder(user);
}
