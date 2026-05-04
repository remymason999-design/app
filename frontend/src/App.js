import { BrowserRouter, Routes, Route, Navigate, useLocation } from "react-router-dom";
import "@/App.css";

import { AuthProvider } from "@/context/AuthContext";
import { Toaster } from "@/components/ui/sonner";
import BottomNav from "@/components/BottomNav";
import ProtectedRoute from "@/components/ProtectedRoute";

import Landing from "@/pages/Landing";
import Login from "@/pages/Login";
import Register from "@/pages/Register";
import OnboardingServices from "@/pages/OnboardingServices";
import OnboardingGenres from "@/pages/OnboardingGenres";
import Discover from "@/pages/Discover";
import Watchlist from "@/pages/Watchlist";
import Savings from "@/pages/Savings";
import Profile from "@/pages/Profile";
import MovieDetail from "@/pages/MovieDetail";
import AuthCallback from "@/pages/AuthCallback";
import Search from "@/pages/Search";
import Admin from "@/pages/Admin";

function AppShell() {
    const location = useLocation();
    // Handle Emergent Google OAuth callback synchronously
    if (location.hash?.includes("session_id=")) return <AuthCallback />;
    return (
        <>
            <Routes>
                <Route path="/" element={<Landing />} />
                <Route path="/login" element={<Login />} />
                <Route path="/register" element={<Register />} />
                <Route
                    path="/onboarding/services"
                    element={
                        <ProtectedRoute requireOnboarding={false}>
                            <OnboardingServices />
                        </ProtectedRoute>
                    }
                />
                <Route
                    path="/onboarding/genres"
                    element={
                        <ProtectedRoute requireOnboarding={false}>
                            <OnboardingGenres />
                        </ProtectedRoute>
                    }
                />
                <Route
                    path="/discover"
                    element={
                        <ProtectedRoute>
                            <Discover />
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
                    path="/movie/:id"
                    element={
                        <ProtectedRoute>
                            <MovieDetail />
                        </ProtectedRoute>
                    }
                />
                <Route
                    path="/search"
                    element={
                        <ProtectedRoute>
                            <Search />
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
                <Route path="*" element={<Navigate to="/" replace />} />
            </Routes>
            <BottomNav />
        </>
    );
}

function App() {
    return (
        <div className="App grain min-h-screen">
            <AuthProvider>
                <BrowserRouter>
                    <AppShell />
                </BrowserRouter>
            </AuthProvider>
            <Toaster theme="dark" position="top-center" />
        </div>
    );
}

export default App;
