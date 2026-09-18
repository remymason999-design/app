import { lazy, Suspense, useEffect, useRef, useState } from "react";
import { BrowserRouter, Routes, Route, Navigate, useLocation } from "react-router-dom";
import { MotionConfig } from "framer-motion";
import "@/App.css";

import { AuthProvider } from "@/context/AuthContext";
import { useAuth } from "@/context/AuthContext";
import { capture, EVENTS } from "@/lib/analytics";
import { Toaster } from "@/components/ui/sonner";
import BottomNav from "@/components/BottomNav";
import ProtectedRoute from "@/components/ProtectedRoute";
import ErrorBoundary from "@/components/ErrorBoundary";
import LaunchAnimation from "@/components/LaunchAnimation";

function usePrefersReducedMotion() {
    const [reduced, setReduced] = useState(() =>
        typeof window !== "undefined" && window.matchMedia
            ? window.matchMedia("(prefers-reduced-motion: reduce)").matches
            : false
    );
    useEffect(() => {
        if (typeof window === "undefined" || !window.matchMedia) return;
        const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
        const handler = (e) => setReduced(e.matches);
        mq.addEventListener?.("change", handler);
        return () => mq.removeEventListener?.("change", handler);
    }, []);
    return reduced;
}

// Critical path — loaded eagerly (auth flow + first screens users see)
import Landing from "@/pages/Landing";
import Login from "@/pages/Login";
import Register from "@/pages/Register";
import AuthCallback from "@/pages/AuthCallback";

// Heavy feature pages — lazy-loaded for faster initial bundle
const Onboarding     = lazy(() => import("@/pages/Onboarding"));
const Discover       = lazy(() => import("@/pages/Discover"));
const Watchlist      = lazy(() => import("@/pages/Watchlist"));
const Watched        = lazy(() => import("@/pages/Watched"));
const Savings        = lazy(() => import("@/pages/Savings"));
const Profile        = lazy(() => import("@/pages/Profile"));
const MovieDetail    = lazy(() => import("@/pages/MovieDetail"));
const Search         = lazy(() => import("@/pages/Search"));
const Admin          = lazy(() => import("@/pages/Admin"));
const ForgotPassword = lazy(() => import("@/pages/ForgotPassword"));
const ResetPassword  = lazy(() => import("@/pages/ResetPassword"));
const Terms          = lazy(() => import("@/pages/Legal").then(m => ({ default: m.Terms })));
const Privacy        = lazy(() => import("@/pages/Legal").then(m => ({ default: m.Privacy })));
const Friends        = lazy(() => import("@/pages/Friends"));
const Compare        = lazy(() => import("@/pages/Compare"));
const ShareLink      = lazy(() => import("@/pages/ShareLink"));
const WatchSmartPlus = lazy(() => import("@/pages/WatchSmartPlus"));

function PageLoader() {
    return (
        <div className="min-h-screen flex items-center justify-center">
            <div className="w-8 h-8 rounded-full border-2 border-white/15 border-t-amber animate-spin" />
        </div>
    );
}

// Wraps a single route surface in an error boundary that renders a compact,
// in-place recovery message (so the bottom nav stays usable) and auto-resets
// whenever the location changes — navigating away clears a crashed surface.
function SurfaceBoundary({ children, title, message }) {
    const location = useLocation();
    return (
        <ErrorBoundary
            variant="surface"
            title={title}
            message={message}
            resetKeys={[location.pathname]}
        >
            {children}
        </ErrorBoundary>
    );
}

function AppShell() {
    const location = useLocation();
    const { user } = useAuth();
    const previousPath = useRef(null);
    const userRef = useRef(user);
    userRef.current = user;
    useEffect(() => {
        let opened = false;
        try { opened = sessionStorage.getItem("ws_app_opened") === "1"; sessionStorage.setItem("ws_app_opened", "1"); } catch {}
        if (!opened) capture(EVENTS.APP_OPENED, {}, { user: userRef.current, allowDuplicate: true });
        capture(EVENTS.SCREEN_VIEWED, {
            screen_name: location.pathname.split("/")[1] || "home",
            previous_screen: previousPath.current ? previousPath.current.split("/")[1] || "home" : undefined,
            source: "router",
        }, { user: userRef.current, dedupeKey: `screen:${location.key || location.pathname}` });
        previousPath.current = location.pathname;
    }, [location.key, location.pathname]);
    return (
        <>
            <Suspense fallback={<PageLoader />}>
                <Routes>
                    <Route path="/" element={<Landing />} />
                    <Route path="/login" element={<Login />} />
                    <Route path="/register" element={<Register />} />
                    <Route path="/forgot-password" element={<ForgotPassword />} />
                    <Route path="/reset-password" element={<ResetPassword />} />
                    <Route path="/terms" element={<Terms />} />
                    <Route path="/privacy" element={<Privacy />} />
                    <Route path="/share/:code" element={<ShareLink />} />
                    <Route path="/auth/callback" element={<AuthCallback />} />
                    <Route
                        path="/onboarding"
                        element={
                            <ProtectedRoute requireOnboarding={false}>
                                <Onboarding />
                            </ProtectedRoute>
                        }
                    />
                    <Route
                        path="/onboarding/services"
                        element={<Navigate to="/onboarding" replace />}
                    />
                    <Route
                        path="/onboarding/genres"
                        element={<Navigate to="/onboarding" replace />}
                    />
                    <Route
                        path="/discover"
                        element={
                            <ProtectedRoute>
                                <SurfaceBoundary
                                    title="Couldn't load your picks"
                                    message="Something went wrong loading recommendations. Try again, or switch tabs."
                                >
                                    <Discover />
                                </SurfaceBoundary>
                            </ProtectedRoute>
                        }
                    />
                    <Route
                        path="/watchlist"
                        element={
                            <ProtectedRoute>
                                <Watchlist />
                            </ProtectedRoute>
                        }
                    />
                    <Route
                        path="/library"
                        element={
                            <ProtectedRoute>
                                <Watchlist />
                            </ProtectedRoute>
                        }
                    />
                    <Route
                        path="/watched"
                        element={
                            <ProtectedRoute>
                                <Watched />
                            </ProtectedRoute>
                        }
                    />
                    <Route
                        path="/savings"
                        element={
                            <ProtectedRoute>
                                <Savings />
                            </ProtectedRoute>
                        }
                    />
                    <Route
                        path="/profile"
                        element={
                            <ProtectedRoute>
                                <Profile />
                            </ProtectedRoute>
                        }
                    />
                    <Route
                        path="/watchsmart-plus"
                        element={
                            <ProtectedRoute>
                                <WatchSmartPlus />
                            </ProtectedRoute>
                        }
                    />
                    <Route
                        path="/movie/:id"
                        element={
                            <ProtectedRoute>
                                <SurfaceBoundary
                                    title="Couldn't load this title"
                                    message="Something went wrong loading the details. Try again, or go back."
                                >
                                    <MovieDetail />
                                </SurfaceBoundary>
                            </ProtectedRoute>
                        }
                    />
                    <Route
                        path="/search"
                        element={
                            <ProtectedRoute>
                                <SurfaceBoundary
                                    title="Search hit a snag"
                                    message="Something went wrong with search. Try again, or go back."
                                >
                                    <Search />
                                </SurfaceBoundary>
                            </ProtectedRoute>
                        }
                    />
                    <Route
                        path="/admin"
                        element={
                            <ProtectedRoute>
                                <Admin />
                            </ProtectedRoute>
                        }
                    />
                    <Route
                        path="/friends"
                        element={
                            <ProtectedRoute>
                                <Friends />
                            </ProtectedRoute>
                        }
                    />
                    <Route
                        path="/compare/:friendId"
                        element={
                            <ProtectedRoute>
                                <Compare />
                            </ProtectedRoute>
                        }
                    />
                    <Route path="*" element={<Navigate to="/" replace />} />
                </Routes>
            </Suspense>
            <BottomNav />
        </>
    );
}

function App() {
    const reducedMotion = usePrefersReducedMotion();
    const [showLaunch, setShowLaunch] = useState(() => {
        try {
            // Dev-only: skip the splash when a dev_token bootstrap is used
            // (automated preview/screenshot verification). No-op in production.
            if (
                process.env.NODE_ENV === "development" &&
                typeof window !== "undefined" &&
                window.location.search.includes("dev_token=")
            ) {
                return false;
            }
            return (
                typeof window !== "undefined" &&
                sessionStorage.getItem("watchsmart_launch_seen") !== "true"
            );
        } catch {
            return false;
        }
    });
    return (
        <ErrorBoundary>
            <MotionConfig reducedMotion={reducedMotion ? "always" : "never"}>
                <div className="App grain min-h-screen">
                    <AuthProvider>
                        <BrowserRouter>
                            <AppShell />
                        </BrowserRouter>
                    </AuthProvider>
                    <Toaster theme="dark" position="top-center" />
                    {showLaunch && (
                        <LaunchAnimation
                            onDone={() => {
                                try {
                                    sessionStorage.setItem("watchsmart_launch_seen", "true");
                                } catch {
                                    /* sessionStorage unavailable — show once, no persistence */
                                }
                                setShowLaunch(false);
                            }}
                        />
                    )}
                </div>
            </MotionConfig>
        </ErrorBoundary>
    );
}

export default App;
