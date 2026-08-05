import React, { useState, useEffect } from 'react'
import Navigation from './components/Navigation'
import HomeFeed from './components/HomeFeed'
import CharacterProfile from './components/CharacterProfile'
import StoryPage from './components/StoryPage'
import StoryLab from './components/StoryLab'
import Messaging from './components/Messaging'
import Notifications from './components/Notifications'
import CharacterCreation from './components/CharacterCreation'

type Screen = 'home' | 'character' | 'story' | 'storylab' | 'messaging' | 'notifications' | 'creation'
type Gem = 'sapphire' | 'emerald' | 'amethyst' | 'ruby' | 'gold' | 'obsidian'

export default function App() {
  const [screen, setScreen] = useState<Screen>('home')
  const [gem, setGem] = useState<Gem>('sapphire')
  const [lightMode, setLightMode] = useState(false)

  useEffect(() => {
    document.documentElement.setAttribute('data-gem', gem)
    document.documentElement.setAttribute('data-mode', lightMode ? 'light' : 'dark')
  }, [gem, lightMode])

  const navigate = (s: Screen) => setScreen(s)

  const screenMap: Record<Screen, React.ReactElement> = {
    home:          <HomeFeed onNavigate={navigate} />,
    character:     <CharacterProfile onNavigate={navigate} />,
    story:         <StoryPage onNavigate={navigate} />,
    storylab:      <StoryLab onNavigate={navigate} />,
    messaging:     <Messaging onNavigate={navigate} />,
    notifications: <Notifications onNavigate={navigate} />,
    creation:      <CharacterCreation onNavigate={navigate} />,
  }

  return (
    <div
      style={{
        display: 'flex',
        width: '100vw',
        height: '100vh',
        overflow: 'hidden',
        background: 'var(--bg)',
        color: 'var(--text)',
      }}
    >
      <Navigation
        active={screen}
        onNavigate={navigate}
        gem={gem}
        onGemChange={setGem}
        lightMode={lightMode}
        onToggleLight={() => setLightMode(l => !l)}
      />
      <main
        style={{
          flex: 1,
          overflow: 'hidden',
          display: 'flex',
          minWidth: 0,
        }}
      >
        {screenMap[screen]}
      </main>
    </div>
  )
}
