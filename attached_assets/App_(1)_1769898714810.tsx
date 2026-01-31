import { useState } from "react";
import { LeftSidebar } from "./components/Layout/LeftSidebar";
import { RightSidebar } from "./components/Layout/RightSidebar";
import { FeedView } from "./components/Feed/FeedView";
import { CharacterProfile } from "./components/Characters/CharacterProfile";
import { CharactersListView } from "./components/Characters/CharactersListView";
import { RealmView } from "./components/Realms/RealmView";
import { SceneComposer } from "./components/Scenes/SceneComposer";
import { MessagesView } from "./components/Messages/MessagesView";
import { LandingPage } from "./components/Landing/LandingPage";
import { SettingsView } from "./components/Settings/SettingsView";
import { WorldbuildingView } from "./components/Worldbuilding/WorldbuildingView";
import { UserProfileView } from "./components/Profile/UserProfileView";

export default function App() {
  const [isLoggedIn, setIsLoggedIn] = useState(false);
  const [currentView, setCurrentView] = useState<string>('feed');
  const [showCharacterProfile, setShowCharacterProfile] = useState(false);

  if (!isLoggedIn) {
    return <LandingPage onEnter={() => setIsLoggedIn(true)} />;
  }

  const renderView = () => {
    switch (currentView) {
      case 'feed':
        return <FeedView />;
      case 'profile':
        return <UserProfileView onNavigate={handleViewChange} />;
      case 'characters':
        return showCharacterProfile ? (
          <CharacterProfile />
        ) : (
          <CharactersListView onViewCharacter={() => setShowCharacterProfile(true)} />
        );
      case 'realms':
        return <RealmView />;
      case 'scenes':
        return <SceneComposer />;
      case 'worldbuilding':
        return <WorldbuildingView />;
      case 'messages':
        return <MessagesView />;
      case 'settings':
        return <SettingsView />;
      default:
        return <FeedView />;
    }
  };

  const handleViewChange = (view: string) => {
    setCurrentView(view);
    if (view !== 'characters') {
      setShowCharacterProfile(false);
    }
  };

  return (
    <div className="min-h-screen bg-[#0A0A0D] relative">
      {/* Background gradient effect */}
      <div className="fixed inset-0 bg-gradient-to-br from-[#0A0A0D] via-[#13131A] to-[#1B4FFF]/10 pointer-events-none" />
      
      {/* Magical ambient particles */}
      <div className="fixed inset-0 opacity-20 pointer-events-none">
        {[...Array(30)].map((_, i) => (
          <div
            key={i}
            className="absolute w-1 h-1 bg-[#3B82F6] rounded-full animate-pulse"
            style={{
              left: `${Math.random() * 100}%`,
              top: `${Math.random() * 100}%`,
              animationDelay: `${Math.random() * 5}s`,
              animationDuration: `${3 + Math.random() * 4}s`
            }}
          />
        ))}
      </div>

      {/* Layout */}
      <div className="relative z-10 flex">
        {currentView !== 'profile' && <LeftSidebar currentView={currentView} onViewChange={handleViewChange} />}
        
        <main className={currentView === 'profile' ? 'flex-1' : 'flex-1 ml-72 mr-80'}>
          {renderView()}
        </main>

        {currentView !== 'profile' && <RightSidebar />}
      </div>
    </div>
  );
}