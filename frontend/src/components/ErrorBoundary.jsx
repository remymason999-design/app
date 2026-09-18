import { Component } from "react";

export default class ErrorBoundary extends Component {
    constructor(props) {
        super(props);
        this.state = { hasError: false, error: null };
    }

    static getDerivedStateFromError(error) {
        return { hasError: true, error };
    }

    componentDidCatch(error, info) {
        if (typeof window !== "undefined" && window.console) {
            console.error("[ErrorBoundary]", error, info?.componentStack);
        }
    }

    componentDidUpdate(prevProps) {
        // Auto-recover when a watched key changes (e.g. route path or item id)
        // so navigating away from a crashed surface clears the error state.
        if (!this.state.hasError) return;
        const a = prevProps.resetKeys || [];
        const b = this.props.resetKeys || [];
        if (a.length !== b.length || a.some((k, i) => k !== b[i])) {
            this.setState({ hasError: false, error: null });
        }
    }

    handleReload = () => {
        try { sessionStorage.clear(); } catch {}
        window.location.assign("/");
    };

    handleRetry = () => {
        this.setState({ hasError: false, error: null });
    };

    render() {
        if (!this.state.hasError) return this.props.children;

        // Compact, in-place fallback for a single surface (Discover/Search/etc.)
        // so the rest of the app (e.g. bottom navigation) stays usable.
        if (this.props.variant === "surface") {
            return (
                <div
                    className="min-h-[50vh] flex items-center justify-center px-6 text-center"
                    data-testid="surface-error"
                >
                    <div className="max-w-xs w-full">
                        <div className="text-4xl mb-3">⚠</div>
                        <h2 className="font-heading text-xl mb-1">
                            {this.props.title || "This section hit a snag"}
                        </h2>
                        <p className="text-sm text-zinc-400 mb-5">
                            {this.props.message ||
                                "Something didn't load right. Try again, or head back and come back to it."}
                        </p>
                        <button
                            onClick={this.handleRetry}
                            className="px-5 py-2.5 rounded-xl bg-amber text-obsidian font-heading text-sm"
                        >
                            Try again
                        </button>
                    </div>
                </div>
            );
        }

        return (
            <div className="min-h-screen flex items-center justify-center px-6 bg-obsidian text-white">
                <div className="max-w-sm w-full text-center">
                    <div className="text-5xl mb-4">⚠</div>
                    <h1 className="font-display text-2xl mb-2">Something went wrong</h1>
                    <p className="text-sm text-zinc-400 mb-6">
                        WatchSmart hit an unexpected error. Your data is safe — try
                        reloading the page.
                    </p>
                    <div className="flex gap-3 justify-center">
                        <button
                            onClick={this.handleRetry}
                            className="px-5 py-2.5 rounded-xl border border-white/15 text-sm hover:bg-white/5"
                        >
                            Try again
                        </button>
                        <button
                            onClick={this.handleReload}
                            className="px-5 py-2.5 rounded-xl bg-amber text-obsidian font-heading text-sm"
                        >
                            Reload app
                        </button>
                    </div>
                </div>
            </div>
        );
    }
}
