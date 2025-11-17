import { useEffect } from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { useAuthStore } from '@/lib/store';
import Layout from '@/components/Layout';
import Login from '@/pages/Login';
import Register from '@/pages/Register';
import Home from '@/pages/Home';
import Realms from '@/pages/Realms';
import RealmDetail from '@/pages/RealmDetail';
import Characters from '@/pages/Characters';
import Profile from '@/pages/Profile';
import UserProfile from '@/pages/UserProfile';
import CharacterProfile from '@/pages/CharacterProfile';
import Discover from '@/pages/Discover';

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
        <Route path="/login" element={isAuthenticated ? <Navigate to="/" /> : <Login />} />
        <Route path="/register" element={isAuthenticated ? <Navigate to="/" /> : <Register />} />

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
          <Route path="/characters" element={<Characters />} />
          <Route path="/profile" element={<Profile />} />
          <Route path="/u/:username" element={<UserProfile />} />
          <Route path="/c/:characterId" element={<CharacterProfile />} />
          <Route path="/discover" element={<Discover />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}

export default App;
