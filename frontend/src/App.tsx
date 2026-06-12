import { useEffect } from 'react';
import { BrowserRouter, Routes, Route, Navigate, useLocation } from 'react-router-dom';
import { useAuthStore } from '@/lib/store';
import Layout from '@/components/Layout';
import ProfileLayout from '@/components/Profile/ProfileLayout';
import Login from '@/pages/Login';
import Register from '@/pages/Register';
import ForgotPassword from '@/pages/ForgotPassword';
import ResetPassword from '@/pages/ResetPassword';
import Home from '@/pages/Home';
import Realms from '@/pages/Realms';
import RealmDetail from '@/pages/RealmDetail';
import Characters from '@/pages/Characters';
import Profile from '@/pages/Profile';
import UserProfile from '@/pages/UserProfile';
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
          <Route path="/workspace" element={<Workspace />} />
          <Route path="/storylab" element={<StoryLab />} />
          <Route path="/storylab/:storyId" element={<StoryLabSession />} />
          <Route path="/rp-stories" element={<RPStories />} />
          <Route path="/rp-stories/:threadId" element={<RPStoryPage />} />
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
          path="/characters/:id"
          element={
            <ProtectedRoute>
              <CharacterDetail />
            </ProtectedRoute>
          }
        />

        <Route
          path="/images"
          element={
            <ProtectedRoute>
              <Images />
            </ProtectedRoute>
          }
        />

        <Route
          path="/images/new"
          element={
            <ProtectedRoute>
              <ImageNew />
            </ProtectedRoute>
          }
        />

        <Route
          path="/studio/18-plus"
          element={
            <ProtectedRoute>
              <Studio18Plus />
            </ProtectedRoute>
          }
        />

        <Route
          path="/editor-studio"
          element={
            <ProtectedRoute>
              <EditorStudio />
            </ProtectedRoute>
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

        <Route
          element={
            <ProtectedRoute>
              <ProfileLayout />
            </ProtectedRoute>
          }
        >
          <Route path="/u/:username" element={<UserProfile />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}

export default App;
