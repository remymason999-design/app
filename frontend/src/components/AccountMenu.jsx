import { useNavigate } from "react-router-dom";
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuLabel,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { LogOut, User as UserIcon, PiggyBank, Heart, Shield, Users } from "lucide-react";
import { useAuth } from "@/context/AuthContext";
import { toast } from "sonner";

export default function AccountMenu() {
    const { user, logout } = useAuth();
    const navigate = useNavigate();

    if (!user) return null;

    const onLogout = async () => {
        await logout();
        toast.success("Signed out");
        navigate("/", { replace: true });
    };

    const initial = (user.name || user.email || "?").slice(0, 1).toUpperCase();

    return (
        <DropdownMenu>
            <DropdownMenuTrigger asChild>
                <button
                    data-testid="account-menu-trigger"
                    aria-label="Account menu"
                    className="h-11 w-11 rounded-full bg-amber flex items-center justify-center text-obsidian font-display text-lg hover:scale-105 active:scale-95 transition-transform amber-glow"
                >
                    {initial}
                </button>
            </DropdownMenuTrigger>
            <DropdownMenuContent
                align="end"
                sideOffset={8}
                className="w-60 bg-velvet border-white/10 text-foreground"
                data-testid="account-menu"
            >
                <DropdownMenuLabel className="px-3 py-2">
                    <div className="font-heading text-sm">{user.name}</div>
                    <div className="text-[11px] text-zinc-400 truncate">{user.email}</div>
                </DropdownMenuLabel>
                <DropdownMenuSeparator className="bg-white/10" />
                <DropdownMenuItem
                    data-testid="menu-profile"
                    onClick={() => navigate("/profile")}
                    className="gap-2 cursor-pointer focus:bg-white/5"
                >
                    <UserIcon className="w-4 h-4" /> Account & preferences
                </DropdownMenuItem>
                <DropdownMenuItem
                    data-testid="menu-watchlist"
                    onClick={() => navigate("/watchlist")}
                    className="gap-2 cursor-pointer focus:bg-white/5"
                >
                    <Heart className="w-4 h-4" /> Watchlist
                </DropdownMenuItem>
                <DropdownMenuItem
                    data-testid="menu-savings"
                    onClick={() => navigate("/savings")}
                    className="gap-2 cursor-pointer focus:bg-white/5"
                >
                    <PiggyBank className="w-4 h-4" /> Savings
                </DropdownMenuItem>
                <DropdownMenuItem
                    data-testid="menu-friends"
                    onClick={() => navigate("/friends")}
                    className="gap-2 cursor-pointer focus:bg-white/5"
                >
                    <Users className="w-4 h-4" /> Friends & compare
                </DropdownMenuItem>
                {user.role === "admin" && (
                    <DropdownMenuItem
                        data-testid="menu-admin"
                        onClick={() => navigate("/admin")}
                        className="gap-2 cursor-pointer focus:bg-white/5 text-amber"
                    >
                        <Shield className="w-4 h-4" /> Admin
                    </DropdownMenuItem>
                )}
                <DropdownMenuSeparator className="bg-white/10" />
                <DropdownMenuItem
                    data-testid="menu-logout"
                    onClick={onLogout}
                    className="gap-2 cursor-pointer focus:bg-red-500/10 text-red-300 focus:text-red-200"
                >
                    <LogOut className="w-4 h-4" /> Sign out
                </DropdownMenuItem>
            </DropdownMenuContent>
        </DropdownMenu>
    );
}
