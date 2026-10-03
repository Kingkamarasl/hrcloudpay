import { Component } from 'react';

export default class ErrorBoundary extends Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error) {
    return { hasError: true, error };
  }

  componentDidCatch(error, info) {
    console.error('UI ErrorBoundary caught:', error, info);
  }

  handleReload = () => {
    this.setState({ hasError: false, error: null });
    window.location.reload();
  };

  render() {
    if (this.state.hasError) {
      return (
        <div className="error-boundary-screen">
          <div className="error-boundary-card">
            <div className="error-boundary-icon">⚠</div>
            <h1>Something went wrong</h1>
            <p>
              An unexpected error occurred in the interface. Your data is safe.
              Try reloading the page. If the problem continues, contact support.
            </p>
            {this.state.error?.message && (
              <pre className="error-boundary-detail">{String(this.state.error.message)}</pre>
            )}
            <button type="button" className="btn btn-primary" onClick={this.handleReload}>
              Reload application
            </button>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}
