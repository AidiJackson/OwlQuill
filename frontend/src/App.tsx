import { useEffect } from 'react';
import { BrowserRouter, Routes, Route, Navigate, useLocation } from 'react-router-dom';
import { useAuthStore } from '@/lib/store';
import Layout from '@/components/Layout';
import Login from '@/pages/Login';
import Register from '@/pages/Register';
import ForgotPassword from '@/pages/ForgotPassword';
import ResetPassword from '@/pages/ResetPassword';
import Home from '@/pages/Home';
import Realms from '@/pages/Realms';
import RealmDetail from '@/pages/RealmDetail';
import Characters from '@/pages/Characters';
import Profile from '@/pages/Profile';
import SceneDetail from '@/pages/SceneDetail';
import CharacterCreationFlow from '@/features/characterCreation/CharacterCreationFlow';
import CharacterDetail from '@/pages/CharacterDetail';
import MessageNew from '@/pages/MessageNew';
import ConversationsList from '@/features/messaging/ConversationsList';
import ConversationThread from '@/features/messaging/ConversationThread';
import Images from '@/pages/Images';
import ImageNew from '@/pages/ImageNew';
import Workspace from '@/pages/Workspace';
import StoryLab from '@/pages/StoryLab';
import StoryLabSession from '@/pages/StoryLabSession';
import RPStories from '@/pages/RPStories';
import RPStoryPage from '@/pages/RPStoryPage';
import StorySpaces from '@/pages/StorySpaces';
import StorySpaceDetail from '@/pages/StorySpaceDetail';
import StorySpacePublish from '@/pages/StorySpacePublish';
import PublishedStoryReader from '@/pages/PublishedStoryReader';
import Notifications from '@/pages/Notifications';
import Studio18Plus from '@/pages/Studio18Plus';
import EditorStudio from '@/pages/EditorStudio';
import WandererNotice from '@/components/WandererNotice';
import { canUseCreatorTools } from '@/lib/entitlements';

function RouteLogger() {
  const location = useLocation();
  useEffect(() => {
    if (import.meta.env.DEV) {
      console.info('ROUTE_CHANGE', location.pathname, Date.now());
    }
  }, [location.pathname]);
  return null;
}

function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated);

  if (!isAuthenticated) {
    return <Navigate to="/login" replace />;
  }

  return <>{children}</>;
}

/**
 * Gate a creator workspace. Authentication alone is not enough — a Wanderer who
 * types the URL must be met with an honest explanation, not the workspace. This
 * is the frontend half of the entitlement; the backend enforces the same rule
 * on the underlying endpoints (a hidden nav link is not access control).
 */
function CreatorRoute({
  workspaceName,
  description,
  children,
}: {
  workspaceName: string;
  description: string;
  children: React.ReactNode;
}) {
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated);
  const isLoading = useAuthStore((state) => state.isLoading);
  const user = useAuthStore((state) => state.user);

  if (!isAuthenticated) {
    return <Navigate to="/login" replace />;
  }
  // Wait for the user to resolve before judging entitlement, so a slow /me
  // fetch doesn't flash the notice at a genuine creator.
  if (isLoading || !user) {
    return null;
  }
  if (!canUseCreatorTools(user)) {
    return <WandererNotice workspaceName={workspaceName} description={description} />;
  }
  return <>{children}</>;
}

function App() {
  const fetchUser = useAuthStore((state) => state.fetchUser);
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated);

  useEffect(() => {
    const token = localStorage.getItem('token');
    if (token) {
      fetchUser();
    }
  }, [fetchUser]);

  return (
    <BrowserRouter>
      <Routes>
        <Route path="*" element={<RouteLogger />} />
        <Route path="/login" element={isAuthenticated ? <Navigate to="/" /> : <Login />} />
        <Route path="/register" element={isAuthenticated ? <Navigate to="/" /> : <Register />} />
        <Route path="/forgot-password" element={isAuthenticated ? <Navigate to="/" /> : <ForgotPassword />} />
        <Route path="/reset-password" element={isAuthenticated ? <Navigate to="/" /> : <ResetPassword />} />

        <Route
          element={
            <ProtectedRoute>
              <Layout />
            </ProtectedRoute>
          }
        >
          <Route path="/" element={<Home />} />
          <Route path="/realms" element={<Realms />} />
          <Route path="/realms/:realmId" element={<RealmDetail />} />
          <Route path="/notifications" element={<Notifications />} />
          <Route path="/spaces" element={<StorySpaces />} />
          <Route path="/spaces/:spaceId" element={<StorySpaceDetail />} />
          <Route path="/spaces/:spaceId/publish" element={<StorySpacePublish />} />
          <Route path="/stories/:storyId" element={<PublishedStoryReader />} />
          <Route path="/characters" element={<Characters />} />
          <Route path="/characters/:id" element={<CharacterDetail />} />
          <Route path="/workspace" element={<CreatorRoute workspaceName="The Workspace" description="The Workspace is where creators manage their characters and craft.">{<Workspace />}</CreatorRoute>} />
          <Route path="/storylab" element={<CreatorRoute workspaceName="StoryLab" description="StoryLab is where creators write and generate long-form stories with their characters.">{<StoryLab />}</CreatorRoute>} />
          <Route path="/storylab/:storyId" element={<CreatorRoute workspaceName="StoryLab" description="StoryLab is where creators write and generate long-form stories with their characters.">{<StoryLabSession />}</CreatorRoute>} />
          <Route path="/rp-stories" element={<CreatorRoute workspaceName="RP Stories" description="RP Stories is where creators run character-to-character roleplay threads.">{<RPStories />}</CreatorRoute>} />
          <Route path="/rp-stories/:threadId" element={<CreatorRoute workspaceName="RP Stories" description="RP Stories is where creators run character-to-character roleplay threads.">{<RPStoryPage />}</CreatorRoute>} />
          <Route path="/scenes/:sceneId" element={<SceneDetail />} />
          <Route path="/profile" element={<Profile />} />
        </Route>

        <Route
          path="/characters/new"
          element={
            <ProtectedRoute>
              <CharacterCreationFlow />
            </ProtectedRoute>
          }
        />

        <Route
          path="/images"
          element={
            <CreatorRoute workspaceName="The Image Library" description="The Image Library is where creators generate and curate imagery for their characters.">
              <Images />
            </CreatorRoute>
          }
        />

        <Route
          path="/images/new"
          element={
            <CreatorRoute workspaceName="The Image Library" description="The Image Library is where creators generate and curate imagery for their characters.">
              <ImageNew />
            </CreatorRoute>
          }
        />

        <Route
          path="/studio/18-plus"
          element={
            <CreatorRoute workspaceName="The 18+ Studio" description="The 18+ Studio is a creator workspace for mature character imagery.">
              <Studio18Plus />
            </CreatorRoute>
          }
        />

        <Route
          path="/editor-studio"
          element={
            <CreatorRoute workspaceName="Editor Studio" description="Editor Studio is where creators refine and edit their generated images.">
              <EditorStudio />
            </CreatorRoute>
          }
        />

        <Route
          path="/messages"
          element={
            <ProtectedRoute>
              <ConversationsList />
            </ProtectedRoute>
          }
        />

        <Route
          path="/messages/new"
          element={
            <ProtectedRoute>
              <MessageNew />
            </ProtectedRoute>
          }
        />

        <Route
          path="/messages/:id"
          element={
            <ProtectedRoute>
              <ConversationThread />
            </ProtectedRoute>
          }
        />

        {/* Identity-first: accounts have no public profile page. Legacy
            /u/{username} links land on the feed. */}
        <Route path="/u/*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  );
}

export default App;
