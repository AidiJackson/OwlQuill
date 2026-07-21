import { useState, useEffect } from 'react';
import { Link, Outlet, useNavigate, useLocation } from 'react-router-dom';
import {
  Home as HomeIcon,
  Globe,
  Users,
  BookOpen,
  PenLine,
  Layers,
  MessagesSquare,
  Image as ImageIcon,
  Wand2,
  MessageCircle,
  Bell,
  CircleUser,
  Menu,
  Sun,
  Moon,
} from 'lucide-react';
import { useAuthStore } from '@/lib/store';
import { useThemeStore, GEMS } from '@/lib/theme';
import { apiClient } from '@/lib/apiClient';
import type { Character } from '@/lib/types';

export default function Layout() {
  const { user, logout, setActiveCharacter } = useAuthStore();
  const { gem, setGem, mode, toggleMode } = useThemeStore();
  const navigate = useNavigate();
  const location = useLocation();
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [messagesSeen, setMessagesSeen] = useState(
    () => localStorage.getItem('ficshon.messages_seen') === 'true'
  );
  const [unreadNotifCount, setUnreadNotifCount] = useState(0);

  // Character switcher (founders only — admins/seeders own several characters)
  const [switcherOpen, setSwitcherOpen] = useState(false);
  const [ownedCharacters, setOwnedCharacters] = useState<Character[]>([]);
  const [switching, setSwitching] = useState(false);

  const isFounder = !!(user?.is_admin || user?.is_seeder);
  // Wanderers (no characters, not founders) only browse — creator tools that
  // need a character are hidden entirely, never shown disabled.
  const isCreator = isFounder || (user?.character_count ?? 0) > 0;
  const activeChar = user?.active_character ?? null;

  useEffect(() => {
    if (!switcherOpen || !isFounder) return;
    apiClient.getCharacters()
      .then(setOwnedCharacters)
      .catch(() => setOwnedCharacters([]));
  }, [switcherOpen, isFounder]);

  const handleSwitchCharacter = async (characterId: number) => {
    setSwitching(true);
    try {
      await setActiveCharacter(characterId);
      setSwitcherOpen(false);
      closeSidebar();
      navigate(`/characters/${characterId}`);
    } catch (e) {
      console.error('Failed to switch character:', e);
    } finally {
      setSwitching(false);
    }
  };

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

  // Premium nav link classes: gem-soft active state, quiet hover elsewhere
  function navCls(active: boolean) {
    return active
      ? 'flex items-center gap-2.5 h-10 px-3.5 rounded-xl bg-gem-soft text-gem text-sm font-medium transition-colors'
      : 'flex items-center gap-2.5 h-10 px-3.5 rounded-xl text-ink-2 text-sm font-medium hover:bg-surface-elevated hover:text-ink transition-colors';
  }

  const iconCls = 'w-[18px] h-[18px] flex-shrink-0';
  const sectionCls =
    'px-3.5 pt-5 pb-1.5 text-[10px] font-mono uppercase tracking-[0.12em] text-ink-3 select-none';

  // Character Owners' Profile destination is their ACTIVE CHARACTER's public
  // profile — the character IS the identity. With no resolvable active
  // character (multi-character account, nothing selected) it falls back to
  // character management so an identity can be chosen.
  const ownerProfilePath = activeChar ? `/characters/${activeChar.id}` : '/characters';

  const p = location.pathname;
  const isHome          = p === '/';
  const isRealms        = p.startsWith('/realms');
  const isSpaces        = p.startsWith('/spaces');
  const isWorkspace     = p.startsWith('/workspace');
  const isStoryLab      = p.startsWith('/storylab');
  const isRPStories     = p.startsWith('/rp-stories');
  const isImages        = p.startsWith('/images');
  const isEditorStudio  = p.startsWith('/editor-studio');
  const isMessages      = p.startsWith('/messages');
  const isNotifications = p.startsWith('/notifications');
  const isProfile       = isCreator ? (!!activeChar && p === ownerProfilePath) : p === '/profile';
  const isChars         = p.startsWith('/characters') && !isProfile;

  const sidebarContent = (
    <>
      <div className="mb-6 px-1">
        <Link to="/" className="flex items-center gap-3" onClick={closeSidebar}>
          <img src="/brand/ficshon-mark-v1.png" alt="Ficshon" className="h-7 w-7 rounded-lg object-contain" />
          <span className="font-serif text-xl font-semibold tracking-tight text-ink">Ficshon</span>
        </Link>
      </div>

      <nav className="space-y-0.5">
        <Link
          to="/"
          className={navCls(isHome)}
          onClick={closeSidebar}
        >
          <HomeIcon className={iconCls} strokeWidth={1.6} />
          Home
        </Link>
        <Link
          to="/realms"
          className={navCls(isRealms)}
          onClick={closeSidebar}
        >
          <Globe className={iconCls} strokeWidth={1.6} />
          Realms
        </Link>
        <Link
          to="/characters"
          className={navCls(isChars)}
          onClick={closeSidebar}
        >
          <Users className={iconCls} strokeWidth={1.6} />
          Characters
        </Link>
        {isCreator && (
          <>
            <div className={sectionCls}>Create</div>
            <Link
              to="/spaces"
              className={navCls(isSpaces)}
              onClick={closeSidebar}
            >
              <BookOpen className={iconCls} strokeWidth={1.6} />
              Story Spaces
            </Link>
            <Link
              to="/workspace"
              className={navCls(isWorkspace)}
              onClick={closeSidebar}
            >
              <PenLine className={iconCls} strokeWidth={1.6} />
              WriteSpace
            </Link>
            <Link
              to="/storylab"
              className={navCls(isStoryLab)}
              onClick={closeSidebar}
            >
              <Layers className={iconCls} strokeWidth={1.6} />
              StoryLab
            </Link>
            <Link
              to="/rp-stories"
              className={navCls(isRPStories)}
              onClick={closeSidebar}
            >
              <MessagesSquare className={iconCls} strokeWidth={1.6} />
              RP Stories
            </Link>
            <Link
              to="/images"
              className={navCls(isImages)}
              onClick={closeSidebar}
            >
              <ImageIcon className={iconCls} strokeWidth={1.6} />
              Images
            </Link>
            <Link
              to="/editor-studio"
              className={navCls(isEditorStudio)}
              onClick={closeSidebar}
            >
              <Wand2 className={iconCls} strokeWidth={1.6} />
              Editor Studio
            </Link>
            <div className={sectionCls}>Personal</div>
            <Link
              to="/messages"
              className={navCls(isMessages)}
              onClick={closeSidebar}
            >
              <MessageCircle className={iconCls} strokeWidth={1.6} />
              Messages
              {!messagesSeen && (
                <span className="w-1.5 h-1.5 rounded-full bg-gem flex-shrink-0" />
              )}
            </Link>
          </>
        )}
        <Link
          to="/notifications"
          className={navCls(isNotifications)}
          onClick={closeSidebar}
        >
          <Bell className={iconCls} strokeWidth={1.6} />
          Notifications
          {unreadNotifCount > 0 && (
            <span className="ml-auto text-[11px] font-mono bg-gem-soft text-gem border border-gem-border rounded-full px-1.5 py-0.5 leading-none">
              {unreadNotifCount > 99 ? '99+' : unreadNotifCount}
            </span>
          )}
        </Link>
        {/* Identity-first: Character Owners' Profile opens their ACTIVE
            CHARACTER's public profile. Wanderers have no public identity —
            they get a private My Account page instead. */}
        {isCreator ? (
          <Link
            to={ownerProfilePath}
            className={navCls(isProfile)}
            onClick={closeSidebar}
          >
            <CircleUser className={iconCls} strokeWidth={1.6} />
            Profile
          </Link>
        ) : (
          <Link
            to="/profile"
            className={navCls(isProfile)}
            onClick={closeSidebar}
          >
            <CircleUser className={iconCls} strokeWidth={1.6} />
            My Account
          </Link>
        )}
      </nav>

      {user && (
        <div className="mt-auto pt-6 space-y-2">
          {/* Gem accent picker + light/dark toggle — cosmetic, every account */}
          <div className="flex items-center gap-2 px-3.5 pb-1">
            <span className="text-[10px] font-mono uppercase tracking-[0.12em] text-ink-3 select-none mr-auto">
              Theme
            </span>
            <button
              type="button"
              onClick={toggleMode}
              aria-label={mode === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
              title={mode === 'dark' ? 'Light mode' : 'Dark mode'}
              className="p-1 rounded-lg text-ink-3 hover:text-ink hover:bg-surface-elevated transition-colors"
            >
              {mode === 'dark' ? (
                <Sun className="w-[15px] h-[15px]" strokeWidth={1.8} />
              ) : (
                <Moon className="w-[15px] h-[15px]" strokeWidth={1.8} />
              )}
            </button>
            {GEMS.map((g) => (
              <button
                key={g.id}
                type="button"
                title={g.label}
                aria-label={`${g.label} theme`}
                onClick={() => setGem(g.id)}
                className={`w-[18px] h-[18px] rounded-full transition-shadow ${
                  gem === g.id ? '' : 'opacity-70 hover:opacity-100'
                }`}
                style={{
                  background: g.color,
                  boxShadow:
                    gem === g.id
                      ? `0 0 0 2px var(--surface), 0 0 0 3.5px ${g.color}`
                      : 'none',
                }}
              />
            ))}
          </div>

          {/* Founder character switcher — the account "is" one character at a
              time; switching feels like changing accounts without logging out. */}
          {isFounder && (
            <div className="relative">
              <button
                onClick={() => setSwitcherOpen((v) => !v)}
                className="w-full flex items-center gap-2.5 px-3 py-2 rounded-xl bg-surface-elevated border border-edge hover:border-gem-border transition-colors text-left"
              >
                {activeChar?.avatar_url ? (
                  <img src={activeChar.avatar_url} alt="" className="w-7 h-7 rounded-lg object-cover flex-shrink-0" />
                ) : (
                  <div className="w-7 h-7 rounded-lg bg-gem-soft flex items-center justify-center text-xs font-semibold text-gem flex-shrink-0">
                    {(activeChar?.name ?? '?').charAt(0)}
                  </div>
                )}
                <span className="flex-1 min-w-0 text-sm text-ink truncate">
                  {activeChar ? activeChar.name : 'Choose character'}
                </span>
                <svg className="w-3.5 h-3.5 text-ink-3 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M8 9l4-4 4 4m0 6l-4 4-4-4" />
                </svg>
              </button>

              {switcherOpen && (
                <>
                  <div className="fixed inset-0 z-40" onClick={() => setSwitcherOpen(false)} />
                  <div className="absolute bottom-full left-0 right-0 mb-2 z-50 bg-surface-overlay border border-edge-md rounded-xl shadow-2xl shadow-black/60 py-1.5 max-h-72 overflow-y-auto">
                    {ownedCharacters.length === 0 && (
                      <p className="px-3 py-2 text-xs text-ink-3">Loading characters…</p>
                    )}
                    {ownedCharacters.map((ch) => (
                      <button
                        key={ch.id}
                        disabled={switching}
                        onClick={() => handleSwitchCharacter(ch.id)}
                        className={`w-full flex items-center gap-2.5 px-3 py-2 hover:bg-surface-elevated transition-colors text-left disabled:opacity-50 ${
                          activeChar?.id === ch.id ? 'text-gem' : 'text-ink'
                        }`}
                      >
                        {ch.avatar_url ? (
                          <img src={ch.avatar_url} alt="" className="w-7 h-7 rounded-lg object-cover flex-shrink-0" />
                        ) : (
                          <div className="w-7 h-7 rounded-lg bg-surface-elevated flex items-center justify-center text-xs font-semibold text-ink-2 flex-shrink-0">
                            {ch.name.charAt(0)}
                          </div>
                        )}
                        <span className="flex-1 min-w-0 text-sm truncate">{ch.name}</span>
                        {activeChar?.id === ch.id && (
                          <svg className="w-4 h-4 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                            <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                          </svg>
                        )}
                      </button>
                    ))}
                  </div>
                </>
              )}
            </div>
          )}

          {/* Wanderers already have "My Account" in the main nav — only
              Character Owners need this extra path to the private account. */}
          {isCreator && (
            <Link
              to="/profile"
              onClick={closeSidebar}
              className="block px-3.5 py-2 text-sm text-ink-3 hover:text-ink rounded-lg hover:bg-surface-elevated transition-colors"
            >
              My Account
            </Link>
          )}
          <button
            onClick={handleLogout}
            className="w-full px-3.5 py-2 text-left text-sm rounded-lg hover:bg-surface-elevated transition-colors text-red-400"
          >
            Logout
          </button>
        </div>
      )}
    </>
  );

  return (
    <div className="min-h-screen flex bg-app">
      {/* Desktop sidebar */}
      <aside className="hidden md:flex md:flex-col w-64 bg-surface border-r border-edge p-4">
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
        className={`fixed inset-y-0 left-0 z-50 w-64 bg-surface border-r border-edge p-4 flex flex-col transform transition-transform duration-200 ease-in-out md:hidden ${
          sidebarOpen ? 'translate-x-0' : '-translate-x-full'
        }`}
      >
        {sidebarContent}
      </aside>

      {/* Main content */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* Mobile top bar with hamburger */}
        <div className="md:hidden flex items-center p-3 bg-surface border-b border-edge">
          <button
            onClick={() => setSidebarOpen(true)}
            className="p-1 text-ink-2 hover:text-ink transition-colors"
            aria-label="Open menu"
          >
            <Menu className="h-6 w-6" strokeWidth={1.8} />
          </button>
          <Link to="/" className="ml-3 flex items-center gap-2">
            <img src="/brand/ficshon-mark-v1.png" alt="Ficshon" className="h-6 w-6 rounded-lg object-contain" />
            <span className="font-serif text-lg font-semibold tracking-tight text-ink">Ficshon</span>
          </Link>
        </div>

        <main className="flex-1 overflow-y-auto">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
