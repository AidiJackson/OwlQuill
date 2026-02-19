import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App.tsx'
import './index.css'

// Boot telemetry (dev-only)
if (import.meta.env.DEV) {
  console.info('APP_BOOT', Date.now(), location.pathname)
  window.addEventListener('error', (e) => console.error('WINDOW_ERROR', e.error || e.message))
  window.addEventListener('unhandledrejection', (e) => console.error('UNHANDLED_REJECTION', e.reason))
}

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
)
