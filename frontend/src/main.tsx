import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App.tsx'
import './fonts.css'
import './index.css'
import { initTheme } from './lib/theme'

// Apply persisted gem/mode theme before first paint (UI v2).
//
// Wrapped even though `initTheme` is now non-throwing on its own. This is the
// last statement before `createRoot().render()`, and anything that throws here
// aborts module evaluation — React never mounts, no error boundary can catch it
// (there is no tree to hold one), and the visitor gets a permanent white page
// on every route, including /login and the public Character Home. The guard is
// the standing invariant for this line, not a patch for today's implementation:
// whoever adds the next pre-mount side effect inherits it.
try {
  initTheme()
} catch {
  /* theme is presentation; the app mounts and renders at its defaults */
}

// Boot telemetry (dev-only)
if (import.meta.env.DEV) {
  console.info('APP_BOOT', Date.now(), location.pathname)
  window.addEventListener('error', (e) => console.error('WINDOW_ERROR', e.error || e.message))
  window.addEventListener('unhandledrejection', (e) => console.error('UNHANDLED_REJECTION', e.reason))
}

// Resolved explicitly rather than with `!`. The assertion compiled away to
// `createRoot(null)`, which throws with a message about the React API rather
// than about the missing element — and on the one line where a throw is
// unrecoverable, the failure should name its own cause.
const rootElement = document.getElementById('root')
if (rootElement) {
  ReactDOM.createRoot(rootElement).render(
    <React.StrictMode>
      <App />
    </React.StrictMode>,
  )
} else {
  console.error('Ficshon could not start: no #root element in the document.')
}
