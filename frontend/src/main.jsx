import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App'
import './styles.css'

/**
 * Last resort. Without this, any exception thrown while rendering unmounts
 * the tree and leaves an empty white page — indistinguishable from "the app
 * never loaded", which is how a blank screen gets reported. Better to show
 * what broke.
 */
class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props)
    this.state = { error: null }
  }

  static getDerivedStateFromError(error) {
    return { error }
  }

  componentDidCatch(error, info) {
    // keep it in the console for whoever is debugging
    console.error('[saavren] render failed:', error, info)
  }

  render() {
    if (!this.state.error) return this.props.children
    return (
      <div style={{
        maxWidth: 640, margin: '12vh auto', padding: 24,
        font: '14px/1.6 system-ui, sans-serif', color: '#e8eaee',
      }}>
        <h1 style={{ fontSize: 20, marginBottom: 8 }}>Saavren could not draw this screen</h1>
        <p style={{ opacity: 0.75, marginBottom: 16 }}>
          The app is running — the page failed while rendering. The details
          below are also in the browser console.
        </p>
        <pre style={{
          background: 'rgba(255,255,255,.06)', padding: 14, borderRadius: 10,
          overflow: 'auto', fontSize: 12, whiteSpace: 'pre-wrap',
        }}>
          {String(this.state.error && (this.state.error.stack || this.state.error))}
        </pre>
        <button
          style={{
            marginTop: 16, padding: '9px 16px', borderRadius: 9, cursor: 'pointer',
            border: '1px solid rgba(255,255,255,.2)', background: 'transparent',
            color: '#e8eaee',
          }}
          onClick={() => window.location.reload()}
        >
          Reload
        </button>
      </div>
    )
  }
}

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <ErrorBoundary>
      <App />
    </ErrorBoundary>
  </React.StrictMode>
)
