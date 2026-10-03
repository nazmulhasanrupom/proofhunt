import { Component, type ReactNode } from "react";

/** One broken page must never turn the whole app black. */
export default class ErrorBoundary extends Component<{ children: ReactNode; resetKey?: string }, { error: Error | null; key?: string }> {
  state: { error: Error | null; key?: string } = { error: null };
  static getDerivedStateFromError(error: Error) { return { error }; }
  static getDerivedStateFromProps(p: { resetKey?: string }, s: { error: Error | null; key?: string }) {
    // moving to another page clears the error
    return p.resetKey !== s.key ? { error: null, key: p.resetKey } : null;
  }
  componentDidCatch(error: Error) { console.error(error); }
  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div className="page"><div className="page-body flex flex-col items-center gap-3 py-16" style={{ color: "var(--text-muted)" }}>
        <p>This page hit an error.</p>
        <code style={{ fontSize: 12, color: "var(--text-faint)" }}>{this.state.error.message}</code>
        <button className="btn-primary" onClick={() => this.setState({ error: null })}>Try again</button>
      </div></div>
    );
  }
}
