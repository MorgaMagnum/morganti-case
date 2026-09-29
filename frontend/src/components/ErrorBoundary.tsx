import { Component, type ReactNode } from 'react'

interface Props {
  fallback: ReactNode
  children: ReactNode
}

/** Keeps a crash in one widget (e.g. the map) from blanking the whole page. */
export default class ErrorBoundary extends Component<Props, { failed: boolean }> {
  state = { failed: false }

  static getDerivedStateFromError() {
    return { failed: true }
  }

  componentDidCatch(error: unknown) {
    console.error('Componente non disponibile:', error)
  }

  render() {
    return this.state.failed ? this.props.fallback : this.props.children
  }
}
