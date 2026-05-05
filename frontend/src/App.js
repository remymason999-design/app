import { BrowserRouter, Routes, Route, Navigate, useLocation } from "react-router-dom";
import "@/App.css";

import { AuthProvider } from "@/context/AuthContext";
import { Toaster } from "@/components/ui/sonner";
import BottomNav from "@/components/BottomNav";
import ProtectedRoute from "@/components/ProtectedRoute";

import Landing from "@/pages/Landing";
import Login from "@/pages/Login";
import Register from "@/pages/Register";
import Onboarding from "@/pages/Onboarding";
import Discover from "@/pages/Discover";
import Watchlist from "@/pages/Watchlist";
import Savings from "@/pages/Savings";
import Profile from "@/pages/Profile";
import MovieDetail from "@/pages/MovieDetail";
import AuthCallback from "@/pages/AuthCallback";
import Search from "@/pages/Search";
import Admin from "@/pages/Admin";
import ForgotPassword from "@/pages/ForgotPassword";
import ResetPassword from "@/pages/ResetPassword";
import Friends from "@/pages/Friends";
import Compare from "@/pages/Compare";
import ShareLink from "@/pages/ShareLink";

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
                <Route path="/forgot-password" element={<ForgotPassword />} />
                <Route path="/reset-password" element={<ResetPassword />} />
                <Route path="/share/:code" element={<ShareLink />} />
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
