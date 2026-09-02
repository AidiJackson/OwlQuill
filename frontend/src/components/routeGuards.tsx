import { Navigate, useLocation } from 'react-router-dom';
import { useAuthStore } from '@/lib/store';
import { buildReturnTo, returnToFromState } from '@/lib/returnTo';
import { canCreateCharacter, canUseCreatorTools } from '@/lib/entitlements';
import type { User } from '@/lib/types';
import WandererNotice from '@/components/WandererNotice';
import BecomeAWriter from '@/pages/BecomeAWriter';

/**
 * The gap between "the app has started" and "we know who this is".
 *
 * Matches the spinner used on the character and notification surfaces, so a
 * cold load on a slow /me looks like the rest of the app rather than a fault.
 */
export function AuthResolving() {
  return (
    <div className="min-h-screen flex items-center justify-center" role="status" aria-label="Loading">
      <div className="w-8 h-8 border-4 border-gem/25 border-t-gem rounded-full animate-spin" />
    </div>
  );
}

/**
 * The one place an unauthenticated visitor is turned away.
 *
 * Two rules, and every other gate in the app is built on top of this one
 * rather than repeating them:
 *
 * 1. Never redirect while auth is still resolving. A redirect issued during
 *    that window is a redirect issued without knowing the answer, and it
 *    lands on a valid session more often than an invalid one.
 * 2. Record where they were going. `/login` gets the interrupted destination
 *    in location state and hands it back after authentication, so a deep link
 *    survives the round trip instead of collapsing to `/`.
 */
export function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const status = useAuthStore((state) => state.status);
  const location = useLocation();

  if (status === 'resolving') {
    return <AuthResolving />;
  }
  if (status !== 'authenticated') {
    return <Navigate to="/login" replace state={{ from: buildReturnTo(location) }} />;
  }
  return <>{children}</>;
}

/**
 * The mirror image: /login, /register and the password flows, which an
 * authenticated visitor has no business seeing.
 *
 * Waits for resolution for the same reason ProtectedRoute does — bouncing
 * someone off /login before /me lands would send them to `/` just as they were
 * about to be sent somewhere better. When a return destination is present it
 * is honoured, so following a deep link with a live session in another tab
 * ends where the link pointed, not at the feed.
 */
export function PublicOnlyRoute({ children }: { children: React.ReactNode }) {
  const status = useAuthStore((state) => state.status);
  const location = useLocation();

  if (status === 'resolving') {
    return <AuthResolving />;
  }
  if (status === 'authenticated') {
    return <Navigate to={returnToFromState(location.state)} replace />;
  }
  return <>{children}</>;
}

/**
 * Apply an entitlement rule to a user we already know is signed in.
 *
 * Only ever rendered inside ProtectedRoute, which is what makes it safe for
 * this to have no opinion about authentication at all: by the time it runs,
 * resolution is complete and the answer was "authenticated". The entitlement
 * rules themselves are unchanged and still live in lib/entitlements.
 */
function EntitlementGate({
  allow,
  fallback,
  children,
}: {
  allow: (user: User | null | undefined) => boolean;
  fallback: React.ReactNode;
  children: React.ReactNode;
}) {
  const user = useAuthStore((state) => state.user);

  // status === 'authenticated' with no user is a window the store never opens
  // — the two are set together — but judging entitlement on a missing user
  // would flash the paywall at a genuine creator, so it waits rather than
  // guesses.
  if (!user) {
    return <AuthResolving />;
  }
  return allow(user) ? <>{children}</> : <>{fallback}</>;
}

/**
 * Gate a creator workspace. Authentication alone is not enough — a Wanderer who
 * types the URL must be met with an honest explanation, not the workspace. This
 * is the frontend half of the entitlement; the backend enforces the same rule
 * on the underlying endpoints (a hidden nav link is not access control).
 */
export function CreatorRoute({
  workspaceName,
  description,
  children,
}: {
  workspaceName: string;
  description: string;
  children: React.ReactNode;
}) {
  return (
    <ProtectedRoute>
      <EntitlementGate
        allow={canUseCreatorTools}
        fallback={<WandererNotice workspaceName={workspaceName} description={description} />}
      >
        {children}
      </EntitlementGate>
    </ProtectedRoute>
  );
}

/**
 * Gate character creation on the Writer entitlement.
 *
 * A Wanderer who reaches /characters/new — by typing it, by a stale link, or
 * by a redirect we missed — gets the upgrade gate, never the creation flow.
 * The backend refuses `POST /characters/` on the same rule, so this is the
 * courteous half of the enforcement, not the enforcement itself.
 */
export function WriterRoute({ children }: { children: React.ReactNode }) {
  return (
    <ProtectedRoute>
      <EntitlementGate allow={canCreateCharacter} fallback={<BecomeAWriter />}>
        {children}
      </EntitlementGate>
    </ProtectedRoute>
  );
}
