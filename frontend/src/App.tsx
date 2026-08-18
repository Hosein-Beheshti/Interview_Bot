import { ChatInterface } from './components/ChatInterface'
import { LoginScreen } from './components/LoginScreen'
import { useAuth } from './hooks/useAuth'
import { useConfig } from './hooks/useConfig'
import './index.css'
import './styles/chat.css'

function App() {
  const auth = useAuth()
  // The server's limits gate the whole app: every input cap and picker length
  // below comes from them, and rendering the form before they arrive would mean
  // inventing values the server never agreed to.
  const { config, status: configStatus, retry: retryConfig } = useConfig()

  if (auth.status === 'loading' || configStatus === 'loading') {
    return (
      <div className="auth-loading">
        <span className="cv-spinner" aria-hidden />
        <span>Loading…</span>
      </div>
    )
  }

  if (configStatus === 'failed' || !config) {
    return (
      <div className="auth-loading">
        <span>Couldn't reach the server.</span>
        <button className="btn-primary" onClick={() => void retryConfig()}>
          Try again
        </button>
      </div>
    )
  }

  if (auth.status === 'signed_out' || !auth.user) {
    return (
      <LoginScreen onLogin={auth.login} error={auth.error} onDismissError={auth.dismissError} />
    )
  }

  return (
    <ChatInterface
      user={auth.user}
      config={config}
      onLogout={auth.logout}
      onCreditsChanged={auth.refresh}
      lastSpend={auth.lastSpend}
      onSpendShown={auth.clearSpend}
    />
  )
}

export default App
