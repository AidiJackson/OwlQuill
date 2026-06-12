import { useState, useEffect } from 'react';
import { Link, Outlet, useNavigate, useLocation } from 'react-router-dom';
import { useAuthStore } from '@/lib/store';
import { apiClient } from '@/lib/apiClient';

export default function Layout() {
  const { user, logout } = useAuthStore();
  const navigate = useNavigate();
  const location = useLocation();
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [messagesSeen, setMessagesSeen] = useState(
    () => localStorage.getItem('ficshon.messages_seen') === 'true'
  );
  const [unreadNotifCount, setUnreadNotifCount] = useState(0);

  useEffect(() => {
    if (location.pathname.startsWith('/messages')) {
      localStorage.setItem('ficshon.messages_seen', 'true');
      setMessagesSeen(true);
    } else if (localStorage.getItem('ficshon.messages_seen') === 'true') {
      setMessagesSeen(true);
    }
  }, [location.pathname]);

  // Fetch unread notification count on mount and when navigating away from /notifications
  useEffect(() => {
    if (!user) return;
    apiClient.getUnreadCount()
      .then(({ count }) => setUnreadNotifCount(count))
      .catch(() => setUnreadNotifCount(0));
  }, [user, location.pathname]);

  const handleLogout = () => {
    logout();
    navigate('/login');
  };

  const closeSidebar = () => setSidebarOpen(false);

  // Returns premium nav link classes based on active state
  function navCls(active: boolean) {
    return active
      ? 'flex items-center gap-2 h-10 px-4 rounded-xl bg-gray-900/60 text-gray-100 border border-purple-500/25 shadow-[0_0_10px_rgba(168,85,247,0.08)] transition-colors'
      : 'flex items-center gap-2 h-10 px-4 rounded-xl text-gray-300 hover:bg-gray-900/40 hover:text-gray-100 transition-colors';
  }

  const p = location.pathname;
  const isHome          = p === '/';
  const isRealms        = p.startsWith('/realms');
  const isSpaces        = p.startsWith('/spaces');
  const isChars         = p.startsWith('/characters');
  const isWorkspace     = p.startsWith('/workspace');
  const isStoryLab      = p.startsWith('/storylab');
  const isRPStories     = p.startsWith('/rp-stories');
  const isImages        = p.startsWith('/images');
  const isEditorStudio  = p.startsWith('/editor-studio');
  const isMessages      = p.startsWith('/messages');
  const isNotifications = p.startsWith('/notifications');
  const isProfile       = p.startsWith('/u/') || p === '/profile';

  const sidebarContent = (
    <>
      <div className="mb-8">
        <Link to="/" className="flex items-center gap-3" onClick={closeSidebar}>
          <img src="/brand/ficshon-mark-v1.png" alt="Ficshon" className="h-7 w-7 rounded-lg object-contain" />
          <span className="text-lg font-semibold tracking-tight">Ficshon</span>
        </Link>
      </div>

      <nav className="space-y-1">
        <Link
          to="/"
          className={navCls(isHome)}
          onClick={closeSidebar}
        >
          Home
        </Link>
        <Link
          to="/realms"
          className={navCls(isRealms)}
          onClick={closeSidebar}
        >
          Realms
        </Link>
        <Link
          to="/spaces"
          className={navCls(isSpaces)}
          onClick={closeSidebar}
        >
          Story Spaces
        </Link>
        <Link
          to="/characters"
          className={navCls(isChars)}
          onClick={closeSidebar}
        >
          Characters
        </Link>
        <Link
          to="/workspace"
          className={navCls(isWorkspace)}
          onClick={closeSidebar}
        >
          WriteSpace
        </Link>
        <Link
          to="/storylab"
          className={navCls(isStoryLab)}
          onClick={closeSidebar}
        >
          StoryLab
        </Link>
        <Link
          to="/rp-stories"
          className={navCls(isRPStories)}
          onClick={closeSidebar}
        >
          RP Stories
        </Link>
        <Link
          to="/images"
          className={navCls(isImages)}
          onClick={closeSidebar}
        >
          Images
        </Link>
        <Link
          to="/editor-studio"
          className={navCls(isEditorStudio)}
          onClick={closeSidebar}
        >
          Editor Studio
        </Link>
        <Link
          to="/messages"
          className={navCls(isMessages)}
          onClick={closeSidebar}
        >
          Messages
          {!messagesSeen && (
            <span className="w-2 h-2 rounded-full bg-emerald-400 flex-shrink-0" />
          )}
        </Link>
        <Link
          to="/notifications"
          className={navCls(isNotifications)}
          onClick={closeSidebar}
        >
          Notifications
          {unreadNotifCount > 0 && (
            <span className="ml-auto text-[11px] font-semibold bg-violet-600 text-white rounded-full px-1.5 py-0.5 leading-none">
              {unreadNotifCount > 99 ? '99+' : unreadNotifCount}
            </span>
          )}
        </Link>
        <Link
          to={user ? `/u/${user.username}` : '/profile'}
          className={navCls(isProfile)}
          onClick={closeSidebar}
        >
          Profile
        </Link>
      </nav>

      {user && (
        <div className="mt-auto pt-8">
          <div className="px-4 py-2 text-sm text-gray-400">
            @{user.username}
          </div>
          <button
            onClick={handleLogout}
            className="w-full px-4 py-2 text-left rounded-lg hover:bg-gray-800 transition-colors text-red-400"
          >
            Logout
          </button>
        </div>
      )}
    </>
  );

  return (
    <div className="min-h-screen flex">
      {/* Desktop sidebar */}
      <aside className="hidden md:flex md:flex-col w-64 bg-gray-900 border-r border-gray-800 p-4">
        {sidebarContent}
      </aside>

      {/* Mobile backdrop */}
      {sidebarOpen && (
        <div
          className="fixed inset-0 bg-black/50 z-40 md:hidden"
          onClick={closeSidebar}
        />
      )}

      {/* Mobile slide-in sidebar */}
      <aside
        className={`fixed inset-y-0 left-0 z-50 w-64 bg-gray-900 border-r border-gray-800 p-4 flex flex-col transform transition-transform duration-200 ease-in-out md:hidden ${
          sidebarOpen ? 'translate-x-0' : '-translate-x-full'
        }`}
      >
        {sidebarContent}
      </aside>

      {/* Main content */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* Mobile top bar with hamburger */}
        <div className="md:hidden flex items-center p-3 bg-gray-900 border-b border-gray-800">
          <button
            onClick={() => setSidebarOpen(true)}
            className="p-1 text-gray-300 hover:text-white transition-colors"
            aria-label="Open menu"
          >
            <svg
              xmlns="http://www.w3.org/2000/svg"
              className="h-6 w-6"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
              strokeWidth={2}
            >
              <path strokeLinecap="round" strokeLinejoin="round" d="M4 6h16M4 12h16M4 18h16" />
            </svg>
          </button>
          <Link to="/" className="ml-3 flex items-center gap-2">
            <img src="/brand/ficshon-mark-v1.png" alt="Ficshon" className="h-6 w-6 rounded-lg object-contain" />
            <span className="text-lg font-semibold tracking-tight">Ficshon</span>
          </Link>
        </div>

        <main className="flex-1 overflow-y-auto">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
