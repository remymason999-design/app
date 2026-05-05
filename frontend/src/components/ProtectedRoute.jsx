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
        const onboarded = user.onboarding_completed === true;
        if (!onboarded && location.pathname !== "/onboarding") {
            return <Navigate to="/onboarding" replace />;
        }
    }
    return children;
}
