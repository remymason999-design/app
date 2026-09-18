import { NavLink, useLocation } from "react-router-dom";
import { Home, Bookmark, Users, Tag, CircleUser } from "lucide-react";
import { useAuth } from "@/context/AuthContext";

const tabs = [
    { to: "/discover", label: "Discover", icon: Home, testId: "tab-discover" },
    { to: "/watchlist", label: "Library", icon: Bookmark, testId: "tab-library" },
    { to: "/friends", label: "Friends", icon: Users, testId: "tab-friends" },
    { to: "/savings", label: "Savings", icon: Tag, testId: "tab-savings" },
    { to: "/profile", label: "Profile", icon: CircleUser, testId: "tab-profile" },
];

export default function BottomNav() {
    const { pathname } = useLocation();
    const { user } = useAuth();
    const hide = ["/", "/login", "/register"].includes(pathname) || pathname.startsWith("/onboarding") || pathname.startsWith("/admin") || pathname.startsWith("/search");
    if (hide) return null;

    const unseen = Number(user?.watchlist_unseen || 0);
    const badgeText = unseen > 99 ? "99+" : String(unseen);

    return (
        <nav
            className="fixed bottom-0 inset-x-0 z-40 border-t border-white/[0.08]"
            data-testid="bottom-nav"
            aria-label="Main navigation"
            style={{
                background: "rgba(9,13,20,0.92)",
                backdropFilter: "blur(20px) saturate(160%)",
                WebkitBackdropFilter: "blur(20px) saturate(160%)",
                paddingBottom: "env(safe-area-inset-bottom, 0px)",
            }}
        >
            <ul className="mx-auto flex w-full max-w-lg items-stretch justify-between px-1">
                {tabs.map(({ to, label, icon: Icon, testId }) => (
                    <li key={to} className="flex-1">
                        <NavLink
                            to={to}
                            data-testid={testId}
                            aria-label={to === "/watchlist" && unseen > 0 ? `${label}, ${badgeText} new items` : label}
                            className={({ isActive }) =>
                                `relative flex min-h-[52px] flex-col items-center justify-center gap-0.5 pt-1.5 pb-1 outline-none transition-colors focus-visible:ring-2 focus-visible:ring-amber/70 focus-visible:ring-offset-0 rounded-md ${
                                    isActive ? "text-amber" : "text-zinc-500 hover:text-zinc-300"
                                }`
                            }
                        >
                            {({ isActive }) => (
                                <>
                                    {/* Active indicator line — not colour-only signalling */}
                                    <span
                                        aria-hidden="true"
                                        className={`absolute top-0 left-1/2 -translate-x-1/2 h-[2px] w-7 rounded-full transition-opacity ${
                                            isActive ? "bg-amber opacity-100" : "opacity-0"
                                        }`}
                                    />
                                    <span className="relative">
                                        <Icon strokeWidth={isActive ? 2 : 1.7} className="h-[19px] w-[19px]" />
                                        {to === "/watchlist" && unseen > 0 && (
                                            <span
                                                data-testid="watchlist-badge"
                                                className="absolute -top-1.5 -right-2.5 min-w-[16px] h-4 px-1 rounded-full bg-amber text-obsidian text-[9px] font-bold leading-4 text-center"
                                            >
                                                {badgeText}
                                            </span>
                                        )}
                                    </span>
                                    <span className="text-[10px] font-medium leading-none tracking-wide">
                                        {label}
                                    </span>
                                </>
                            )}
                        </NavLink>
                    </li>
                ))}
            </ul>
        </nav>
    );
}
