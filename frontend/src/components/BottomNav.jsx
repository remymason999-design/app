import { NavLink, useLocation } from "react-router-dom";
import { Compass, Heart, PiggyBank, User } from "lucide-react";

const tabs = [
    { to: "/discover", label: "Discover", icon: Compass, testId: "tab-discover" },
    { to: "/watchlist", label: "Watchlist", icon: Heart, testId: "tab-watchlist" },
    { to: "/savings", label: "Savings", icon: PiggyBank, testId: "tab-savings" },
    { to: "/profile", label: "Profile", icon: User, testId: "tab-profile" },
];

export default function BottomNav() {
    const { pathname } = useLocation();
    const hide = ["/", "/login", "/register"].includes(pathname) || pathname.startsWith("/onboarding") || pathname.startsWith("/admin");
    if (hide) return null;
    return (
        <nav
            className="fixed bottom-0 inset-x-0 z-40 glass-strong"
            data-testid="bottom-nav"
            style={{ paddingBottom: "env(safe-area-inset-bottom, 0)" }}
        >
            <ul className="max-w-md mx-auto flex justify-around items-stretch px-2 py-2">
                {tabs.map(({ to, label, icon: Icon, testId }) => (
                    <li key={to} className="flex-1">
                        <NavLink
                            to={to}
                            data-testid={testId}
                            className={({ isActive }) =>
                                `flex flex-col items-center justify-center gap-1 py-2 rounded-xl transition-colors ${
                                    isActive ? "text-amber" : "text-zinc-500 hover:text-zinc-200"
                                }`
                            }
                        >
                            <Icon strokeWidth={1.6} className="h-5 w-5" />
                            <span className="text-[10px] tracking-wide uppercase font-medium">
                                {label}
                            </span>
                        </NavLink>
                    </li>
                ))}
            </ul>
        </nav>
    );
}
