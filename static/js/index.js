// index.js — bootstraps the React app

// A render error in one view shows a message instead of blanking the whole app.
class ErrorBoundary extends React.Component {
  constructor(props) { super(props); this.state = { error: null }; }
  static getDerivedStateFromError(error) { return { error }; }
  componentDidCatch(error, info) { console.error(error, info); }
  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div className="empty">
        <h3>Something went wrong</h3>
        <p style={{maxWidth:480}}>{String(this.state.error.message || this.state.error)}</p>
        <button className="btn-ghost" onClick={() => this.setState({ error: null })}>Try again</button>
      </div>
    );
  }
}

const root = ReactDOM.createRoot(document.getElementById("root"));
root.render(
  <ErrorBoundary>
    <AppProvider>
      <App/>
    </AppProvider>
  </ErrorBoundary>
);
