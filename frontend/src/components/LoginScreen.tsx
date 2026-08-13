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
        <p>Practice the interview before it counts.</p>

        <ul className="login-points">
          <li><CheckIcon />Questions built from the job description and your CV</li>
          <li><CheckIcon />Spoken both ways — answer out loud or type</li>
          <li><CheckIcon />A score after every answer, and a summary at the end</li>
        </ul>

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
          Signing in with Google only identifies you and keeps your interview
          history. We never post on your behalf.
        </p>
      </div>
    </div>
  )
}

/** Tick for the value list. Decorative — the text beside it carries the point. */
function CheckIcon() {
  return (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor"
      strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <path d="M20 6 9 17l-5-5" />
    </svg>
  )
}
