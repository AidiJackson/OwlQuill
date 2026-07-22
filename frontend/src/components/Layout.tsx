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
  ChevronDown,
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

  // Cinematic top-bar menus (Character Home shell only)
  const [createOpen, setCreateOpen] = useState(false);
  const [accountOpen, setAccountOpen] = useState(false);

  // Shown under the sidebar Profile item when a multi-character account
  // clicks Profile with no active character selected
  const [profileHint, setProfileHint] = useState('');

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
  // Character Home uses the cinematic shell: slim top bar, no desktop
  // sidebar, so the hero can span the full content width. Every other
  // route keeps the standard sidebar shell. (/characters/new lives outside
  // Layout entirely, so this only ever matches /characters/:id.)
  const isCinematic     = p.startsWith('/characters/');
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

  // Creator Profile click. With an active character the Link navigates
  // normally. A multi-character account with nothing selected has no
  // resolvable profile — the /characters fallback is a silent no-op when
  // already there — so surface the existing selection flow instead:
  // founders get the character switcher, others a brief prompt.
  const handleProfileClick = (e: React.MouseEvent<HTMLAnchorElement>) => {
    if (activeChar) {
      closeSidebar();
      setAccountOpen(false);
      return;
    }
    e.preventDefault();
    setAccountOpen(false);
    if (isFounder) {
      setSwitcherOpen(true);
    } else {
      setProfileHint('Choose a character first.');
      window.setTimeout(() => setProfileHint(''), 3000);
      if (p !== '/characters') {
        closeSidebar();
        navigate('/characters');
      }
    }
  };

  // Mode toggle + gem dots — shared by the sidebar footer and the cinematic
  // top bar's account menu so both shells drive the same theme store.
  const themeControls = (
    <>
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
    </>
  );

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
          <>
            <Link
              to={ownerProfilePath}
              className={navCls(isProfile)}
              onClick={handleProfileClick}
            >
              <CircleUser className={iconCls} strokeWidth={1.6} />
              Profile
            </Link>
            {profileHint && (
              <p className="px-3.5 pt-1 text-xs text-ink-3">{profileHint}</p>
            )}
          </>
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
          {/* Permanent appearance section — gem picker + light/dark toggle */}
          <div className="flex items-center gap-2 px-3.5 pb-1">
            <span className="text-[10px] font-mono uppercase tracking-[0.12em] text-ink-3 select-none mr-auto">
              Appearance
            </span>
            {themeControls}
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

  // Compact link + icon-button styles for the cinematic top bar
  const topLinkCls = (active: boolean) =>
    active
      ? 'inline-flex items-center h-8 px-3 rounded-lg bg-gem-soft text-gem text-sm font-medium transition-colors'
      : 'inline-flex items-center h-8 px-3 rounded-lg text-ink-2 text-sm font-medium hover:bg-surface-elevated hover:text-ink transition-colors';
  const topIconCls =
    'relative p-2 rounded-lg text-ink-2 hover:text-ink hover:bg-surface-elevated transition-colors';
  const menuItemCls =
    'flex items-center gap-2.5 px-3 py-2 text-sm text-ink-2 hover:bg-surface-elevated hover:text-ink transition-colors';

  /* Cinematic top bar (Character Home shell) — same nav sources, stores and
     gating as the sidebar, recomposed as a slim toolbar. z-30 keeps it under
     every overlay layer (drawers, modals, lightbox all use z-40/z-50). */
  const cinematicTopBar = (
    <header className="sticky top-0 z-30 bg-surface border-b border-edge">
      <div className="flex items-center gap-1.5 h-12 px-3 sm:px-5">
        {/* Mobile drawer trigger — the established drawer carries the full nav */}
        <button
          onClick={() => setSidebarOpen(true)}
          className="md:hidden p-1 mr-1 text-ink-2 hover:text-ink transition-colors"
          aria-label="Open menu"
        >
          <Menu className="h-6 w-6" strokeWidth={1.8} />
        </button>
        <Link to="/" className="flex items-center gap-2 flex-shrink-0">
          <img src="/brand/ficshon-mark-v1.png" alt="Ficshon" className="h-6 w-6 rounded-lg object-contain" />
          <span className="font-serif text-lg font-semibold tracking-tight text-ink">Ficshon</span>
        </Link>

        {/* Primary destinations */}
        <nav className="hidden md:flex items-center gap-1 ml-4 min-w-0">
          <Link to="/" className={topLinkCls(isHome)}>Commons</Link>
          <Link to="/realms" className={topLinkCls(isRealms)}>Realms</Link>
          <Link to="/characters" className={topLinkCls(isChars)}>Characters</Link>
          {isCreator && (
            <div className="relative">
              <button
                onClick={() => setCreateOpen((v) => !v)}
                className={`${topLinkCls(false)} gap-1`}
              >
                Create
                <ChevronDown className="w-3.5 h-3.5" strokeWidth={1.8} />
              </button>
              {createOpen && (
                <>
                  <div className="fixed inset-0 z-40" onClick={() => setCreateOpen(false)} />
                  <div className="absolute top-full left-0 mt-2 z-50 w-48 bg-surface-overlay border border-edge-md rounded-xl shadow-2xl shadow-black/60 py-1.5">
                    <Link to="/spaces" className={menuItemCls} onClick={() => setCreateOpen(false)}>
                      <BookOpen className={iconCls} strokeWidth={1.6} />Story Spaces
                    </Link>
                    <Link to="/workspace" className={menuItemCls} onClick={() => setCreateOpen(false)}>
                      <PenLine className={iconCls} strokeWidth={1.6} />WriteSpace
                    </Link>
                    <Link to="/storylab" className={menuItemCls} onClick={() => setCreateOpen(false)}>
                      <Layers className={iconCls} strokeWidth={1.6} />StoryLab
                    </Link>
                    <Link to="/rp-stories" className={menuItemCls} onClick={() => setCreateOpen(false)}>
                      <MessagesSquare className={iconCls} strokeWidth={1.6} />RP Stories
                    </Link>
                    <Link to="/images" className={menuItemCls} onClick={() => setCreateOpen(false)}>
                      <ImageIcon className={iconCls} strokeWidth={1.6} />Images
                    </Link>
                    <Link to="/editor-studio" className={menuItemCls} onClick={() => setCreateOpen(false)}>
                      <Wand2 className={iconCls} strokeWidth={1.6} />Editor Studio
                    </Link>
                  </div>
                </>
              )}
            </div>
          )}
        </nav>

        <div className="flex items-center gap-1 ml-auto flex-shrink-0">
          {/* Founder character switcher — same handler as the sidebar; the
              drawer version covers narrow widths */}
          {isFounder && (
            <div className="relative hidden md:block mr-1">
              <button
                onClick={() => setSwitcherOpen((v) => !v)}
                className="flex items-center gap-2 pl-1.5 pr-2 py-1 rounded-lg bg-surface-elevated border border-edge hover:border-gem-border transition-colors"
              >
                {activeChar?.avatar_url ? (
                  <img src={activeChar.avatar_url} alt="" className="w-6 h-6 rounded-md object-cover flex-shrink-0" />
                ) : (
                  <div className="w-6 h-6 rounded-md bg-gem-soft flex items-center justify-center text-xs font-semibold text-gem flex-shrink-0">
                    {(activeChar?.name ?? '?').charAt(0)}
                  </div>
                )}
                <span className="hidden lg:block max-w-[130px] truncate text-sm text-ink">
                  {activeChar ? activeChar.name : 'Choose character'}
                </span>
                <ChevronDown className="w-3.5 h-3.5 text-ink-3 flex-shrink-0" strokeWidth={2} />
              </button>
              {switcherOpen && (
                <>
                  <div className="fixed inset-0 z-40" onClick={() => setSwitcherOpen(false)} />
                  <div className="absolute top-full right-0 mt-2 z-50 w-60 bg-surface-overlay border border-edge-md rounded-xl shadow-2xl shadow-black/60 py-1.5 max-h-72 overflow-y-auto">
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

          {isCreator && (
            <Link to="/messages" className={topIconCls} aria-label="Messages">
              <MessageCircle className="w-5 h-5" strokeWidth={1.6} />
              {!messagesSeen && (
                <span className="absolute top-1.5 right-1.5 w-1.5 h-1.5 rounded-full bg-gem" />
              )}
            </Link>
          )}
          <Link to="/notifications" className={topIconCls} aria-label="Notifications">
            <Bell className="w-5 h-5" strokeWidth={1.6} />
            {unreadNotifCount > 0 && (
              <span className="absolute -top-0.5 -right-0.5 text-[10px] font-mono bg-gem-soft text-gem border border-gem-border rounded-full px-1 py-0.5 leading-none">
                {unreadNotifCount > 99 ? '99+' : unreadNotifCount}
              </span>
            )}
          </Link>

          {/* Account menu — profile access, theme controls, logout */}
          <div className="relative hidden md:block">
            <button
              onClick={() => setAccountOpen((v) => !v)}
              className={topIconCls}
              aria-label="Account"
            >
              <CircleUser className="w-5 h-5" strokeWidth={1.6} />
            </button>
            {accountOpen && (
              <>
                <div className="fixed inset-0 z-40" onClick={() => setAccountOpen(false)} />
                <div className="absolute top-full right-0 mt-2 z-50 w-56 bg-surface-overlay border border-edge-md rounded-xl shadow-2xl shadow-black/60 py-1.5">
                  {isCreator ? (
                    <>
                      <Link to={ownerProfilePath} className={menuItemCls} onClick={handleProfileClick}>
                        <CircleUser className={iconCls} strokeWidth={1.6} />Profile
                      </Link>
                      <Link to="/profile" className={menuItemCls} onClick={() => setAccountOpen(false)}>
                        My Account
                      </Link>
                    </>
                  ) : (
                    <Link to="/profile" className={menuItemCls} onClick={() => setAccountOpen(false)}>
                      <CircleUser className={iconCls} strokeWidth={1.6} />My Account
                    </Link>
                  )}
                  <div className="my-1.5 border-t border-edge" />
                  <div className="flex items-center gap-2 px-3 py-2">
                    <span className="text-[10px] font-mono uppercase tracking-[0.12em] text-ink-3 select-none mr-auto">
                      Appearance
                    </span>
                    {themeControls}
                  </div>
                  <div className="my-1.5 border-t border-edge" />
                  <button
                    onClick={handleLogout}
                    className="w-full px-3 py-2 text-left text-sm hover:bg-surface-elevated transition-colors text-red-400"
                  >
                    Logout
                  </button>
                </div>
              </>
            )}
          </div>
        </div>
      </div>
    </header>
  );

  return (
    <div className="min-h-screen flex bg-app">
      {/* Desktop sidebar — every route except the cinematic Character Home */}
      {/* sticky + h-screen pins the sidebar to the viewport while the body
          scrolls; without an explicit height it stretches to full document
          height and the bottom Appearance/switcher block becomes unreachable
          on long pages */}
      {!isCinematic && (
        <aside className="hidden md:flex md:flex-col w-64 md:sticky md:top-0 md:h-screen md:overflow-y-auto bg-surface border-r border-edge p-4">
          {sidebarContent}
        </aside>
      )}

      {/* Mobile backdrop */}
      {sidebarOpen && (
        <div
          className="fixed inset-0 bg-black/50 z-40 md:hidden"
          onClick={closeSidebar}
        />
      )}

      {/* Mobile slide-in sidebar */}
      <aside
        className={`fixed inset-y-0 left-0 z-50 w-64 overflow-y-auto bg-surface border-r border-edge p-4 flex flex-col transform transition-transform duration-200 ease-in-out md:hidden ${
          sidebarOpen ? 'translate-x-0' : '-translate-x-full'
        }`}
      >
        {sidebarContent}
      </aside>

      {/* Main content */}
      <div className="flex-1 flex flex-col min-w-0">
        {isCinematic ? (
          cinematicTopBar
        ) : (
          /* Mobile top bar with hamburger */
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
        )}

        <main className="flex-1 overflow-y-auto">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
