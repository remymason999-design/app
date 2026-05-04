import { Navigate, useLocation } from "react-router-dom";
import { useAuth } from "@/context/AuthContext";

export default function ProtectedRoute({ children, requireOnboarding = true }) {
    const { user, loading } = useAuth();
    const location = useLocation();

    if (loading) {
        return (
            <div className="min-h-screen flex items-center justify-center bg-obsidian">
                <div className="h-10 w-10 rounded-full border-2 border-amber border-t-transparent animate-spin" />
            </div>
        );
    }
    if (!user) return <Navigate to="/login" state={{ from: location }} replace />;

    if (requireOnboarding) {
        const needsServices = !(user.subscriptions?.length > 0);
        const needsGenres = !(user.genres?.length > 0);
        if (needsServices && location.pathname !== "/onboarding/services") {
            return <Navigate to="/onboarding/services" replace />;
        }
        if (!needsServices && needsGenres && location.pathname !== "/onboarding/genres") {
            return <Navigate to="/onboarding/genres" replace />;
        }
    }
    return children;
}
