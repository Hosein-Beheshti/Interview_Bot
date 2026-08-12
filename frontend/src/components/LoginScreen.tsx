import { GoogleLogin, CredentialResponse } from '@react-oauth/google'
import { BrandMark } from './icons'
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
        <div className="welcome-orb"><BrandMark size={26} /></div>
        <h1>Warmup</h1>
        <p>
          Practice technical interviews with spoken questions, per-answer scoring,
          and a written summary. Sign in to begin.
        </p>

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
