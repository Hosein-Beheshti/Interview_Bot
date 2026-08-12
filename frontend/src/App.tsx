import { ChatInterface } from './components/ChatInterface'
import { LoginScreen } from './components/LoginScreen'
import { useAuth } from './hooks/useAuth'
import './index.css'
import './styles/chat.css'

function App() {
  const auth = useAuth()

  if (auth.status === 'loading') {
    return (
      <div className="auth-loading">
        <span className="cv-spinner" aria-hidden />
        <span>Loading…</span>
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
      onLogout={auth.logout}
      onCreditsChanged={auth.refresh}
      lastSpend={auth.lastSpend}
      onSpendShown={auth.clearSpend}
    />
  )
}

export default App
