import { GoogleLogin, CredentialResponse } from '@react-oauth/google'
import '../styles/chat.css'

interface LoginScreenProps {
  onLogin: (idToken: string) => void
  error?: string | null
  onDismissError?: () => void
}

export function LoginScreen({ onLogin, error, onDismissError }: LoginScreenProps) {
  const handleSuccess = (credential: CredentialResponse) => {
    if (credential.credential) onLogin(credential.credential)
  }

  return (
    <div className="login-screen">
      <div className="login-card">
        <div className="welcome-orb"><span>🎯</span></div>
        <h1>AI Interviewer</h1>
        <p>Sign in to practice technical interviews with real-time AI feedback and voice interaction.</p>

        <div className="login-button-wrap">
          <GoogleLogin
            onSuccess={handleSuccess}
            onError={() => undefined}
            theme="filled_black"
            shape="pill"
            size="large"
          />
        </div>

        {error && (
          <div className="error-strip login-error">
            <span>{error}</span>
            {onDismissError && (
              <button className="strip-btn" onClick={onDismissError}>Dismiss</button>
            )}
          </div>
        )}

        <p className="privacy-note">
          We only use your Google account to identify you and keep your interview
          history. We never post on your behalf.
        </p>
      </div>
    </div>
  )
}
