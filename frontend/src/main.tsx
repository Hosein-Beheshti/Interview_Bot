import React from 'react'
import ReactDOM from 'react-dom/client'
import { GoogleOAuthProvider } from '@react-oauth/google'
import App from './App.tsx'

const GOOGLE_CLIENT_ID = import.meta.env.VITE_GOOGLE_CLIENT_ID

if (!GOOGLE_CLIENT_ID) {
  // Fails loudly in development rather than silently rendering a login button
  // that can never succeed. In production this should always be set via the
  // Docker build arg (see frontend/.env.example).
  console.error(
    'VITE_GOOGLE_CLIENT_ID is not set — Google sign-in will not work. ' +
      'Copy frontend/.env.example to frontend/.env and fill it in.',
  )
}

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <GoogleOAuthProvider clientId={GOOGLE_CLIENT_ID ?? ''}>
      <App />
    </GoogleOAuthProvider>
  </React.StrictMode>,
)
