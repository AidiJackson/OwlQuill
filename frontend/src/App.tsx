import { useEffect } from 'react';
import { BrowserRouter, Routes, Route, Navigate, useLocation } from 'react-router-dom';
import { useAuthStore } from '@/lib/store';
import { ProtectedRoute, PublicOnlyRoute, CreatorRoute, WriterRoute } from '@/components/routeGuards';
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
import AdminCreator from '@/pages/AdminCreator';
import BecomeAWriter from '@/pages/BecomeAWriter';

function RouteLogger() {
  const location = useLocation();
  useEffect(() => {
    if (import.meta.env.DEV) {
      console.info('ROUTE_CHANGE', location.pathname, Date.now());
    }
  }, [location.pathname]);
  return null;
}

function App() {
  const initializeAuth = useAuthStore((state) => state.initializeAuth);

  // One resolution pass per app start. The store already opened in the right
  // status from token presence alone, so this confirms the token rather than
  // discovering it — nothing renders a redirect while it is in flight.
  useEffect(() => {
    initializeAuth();
  }, [initializeAuth]);

  return (
    <BrowserRouter>
      <Routes>
        <Route path="*" element={<RouteLogger />} />
        <Route path="/login" element={<PublicOnlyRoute><Login /></PublicOnlyRoute>} />
        <Route path="/register" element={<PublicOnlyRoute><Register /></PublicOnlyRoute>} />
        <Route path="/forgot-password" element={<PublicOnlyRoute><ForgotPassword /></PublicOnlyRoute>} />
        <Route path="/reset-password" element={<PublicOnlyRoute><ResetPassword /></PublicOnlyRoute>} />

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
          <Route path="/become-a-writer" element={<BecomeAWriter />} />
        </Route>

        <Route
          path="/characters/new"
          element={
            <WriterRoute>
              <CharacterCreationFlow />
            </WriterRoute>
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

        {/* Admin Creator — experimental four-reference workflow, founder/seeder
            only. CreatorRoute keeps Wanderers out of the route entirely; the
            page itself then re-checks canUseAdminCreator, so an ordinary
            creator who reaches the URL gets "Not available" rather than the
            tool. The server authorises every call independently. */}
        <Route
          path="/admin-creator"
          element={
            <CreatorRoute workspaceName="Admin Creator" description="Admin Creator is an internal tool for testing image generation workflows.">
              <AdminCreator />
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
