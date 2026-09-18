import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Eye, EyeOff } from "lucide-react";
import { motion } from "framer-motion";
import { apiGet, apiPost, formatApiError, setToken } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { toast } from "sonner";
import { capture, switchIdentity, EVENTS } from "@/lib/analytics";

export default function Login() {
    const navigate = useNavigate();
    const { setUser } = useAuth();
    const [email, setEmail] = useState("");
    const [password, setPassword] = useState("");
    const [showPwd, setShowPwd] = useState(false);
    const [loading, setLoading] = useState(false);

    const onSubmit = async (e) => {
        e.preventDefault();
        setLoading(true);
        try {
            const data = await apiPost("/auth/login", { email, password });
            if (data.access_token) setToken(data.access_token);
            setUser(data.user);
            switchIdentity(data.user);
            capture(EVENTS.LOGIN, { method: "password" }, { user: data.user });
            toast.success(`Welcome back, ${data.user.name}`);
            let pendingCode = null;
            try { pendingCode = sessionStorage.getItem("pending_share_code"); } catch {}
            if (pendingCode) {
                navigate(`/share/${pendingCode}`);
                return;
            }
            const next = data.user.onboarding_completed ? "/discover" : "/onboarding";
            navigate(next);
        } catch (err) {
            toast.error(formatApiError(err.response?.data?.detail) || "Login failed");
        } finally {
            setLoading(false);
        }
    };

    const onGoogle = async () => {
        try {
            const redirectUri = window.location.origin + "/auth/callback";
            const { url } = await apiGet(`/auth/google/url?redirect_uri=${encodeURIComponent(redirectUri)}`);
            window.location.href = url;
        } catch {
            toast.error("Google sign-in is not available right now");
        }
    };

    const onApple = async () => {
        try {
            const { url } = await apiGet(`/auth/apple/url?origin=${encodeURIComponent(window.location.origin)}`);
            window.location.href = url;
        } catch {
            toast.error("Apple sign-in is not available right now");
        }
    };

    return (
        <div className="min-h-screen px-6 py-12 max-w-md mx-auto flex flex-col">
            <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.4 }}>
                <Link to="/" className="text-xs uppercase tracking-[0.25em] text-zinc-500" data-testid="link-home">
                    WatchSmart
                </Link>
                <h1 className="font-display text-4xl mt-6 mb-2">Welcome back</h1>
                <p className="text-zinc-400 mb-8">Pick up where you left off.</p>

                <form onSubmit={onSubmit} className="space-y-4" data-testid="login-form">
                    <Field label="Email">
                        <input
                            type="email"
                            required
                            autoComplete="email"
                            value={email}
                            onChange={(e) => setEmail(e.target.value)}
                            data-testid="login-email"
                            className="input-field"
                        />
                    </Field>
                    <Field label="Password">
                        <div className="relative">
                            <input
                                type={showPwd ? "text" : "password"}
                                required
                                autoComplete="current-password"
                                value={password}
                                onChange={(e) => setPassword(e.target.value)}
                                data-testid="login-password"
                                className="input-field pr-12"
                            />
                            <button
                                type="button"
                                onClick={() => setShowPwd((s) => !s)}
                                className="absolute right-3 top-1/2 -translate-y-1/2 text-zinc-500 hover:text-zinc-200"
                                aria-label="toggle password"
                            >
                                {showPwd ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                            </button>
                        </div>
                    </Field>
                    <button
                        type="submit"
                        disabled={loading}
                        data-testid="login-submit"
                        className="w-full bg-amber hover:bg-amber-600 disabled:opacity-60 text-obsidian font-heading text-base py-4 rounded-2xl transition-colors amber-glow"
                    >
                        {loading ? "Signing in…" : "Sign in"}
                    </button>
                    <div className="text-right">
                        <Link to="/forgot-password" className="text-xs text-zinc-400 hover:text-amber" data-testid="link-forgot">
                            Forgot password?
                        </Link>
                    </div>
                </form>

                <Divider>or</Divider>

                <div className="space-y-3">
                    <button
                        onClick={onGoogle}
                        data-testid="login-google"
                        className="w-full glass rounded-2xl py-4 flex items-center justify-center gap-3 font-medium hover:bg-white/5 transition-colors"
                    >
                        <GoogleIcon />
                        <span>Continue with Google</span>
                    </button>
                    <button
                        onClick={onApple}
                        data-testid="login-apple"
                        className="w-full bg-white text-black rounded-2xl py-4 flex items-center justify-center gap-3 font-medium hover:bg-zinc-100 transition-colors"
                    >
                        <AppleIcon className="h-5 w-5 fill-black" />
                        <span>Continue with Apple</span>
                    </button>
                </div>

                <p className="text-center text-sm text-zinc-500 mt-8">
                    No account?{" "}
                    <Link to="/register" className="text-amber hover:underline" data-testid="link-register">
                        Create one
                    </Link>
                </p>
            </motion.div>
            <FieldStyles />
        </div>
    );
}

export function Field({ label, children }) {
    return (
        <label className="block">
            <span className="block text-xs uppercase tracking-[0.18em] text-zinc-500 mb-2">{label}</span>
            {children}
        </label>
    );
}

export function Divider({ children }) {
    return (
        <div className="flex items-center gap-3 my-6">
            <div className="flex-1 h-px bg-white/10" />
            <span className="text-xs uppercase tracking-widest text-zinc-600">{children}</span>
            <div className="flex-1 h-px bg-white/10" />
        </div>
    );
}

export function GoogleIcon() {
    return (
        <svg viewBox="0 0 48 48" className="h-5 w-5">
            <path fill="#FFC107" d="M43.6 20.5H42V20H24v8h11.3c-1.6 4.6-6 8-11.3 8-6.6 0-12-5.4-12-12s5.4-12 12-12c3 0 5.7 1.1 7.8 3l5.7-5.7C34 5.7 29.3 4 24 4 12.9 4 4 12.9 4 24s8.9 20 20 20c11 0 19.7-8 19.7-20 0-1.3-.1-2.3-.1-3.5z"/>
            <path fill="#FF3D00" d="M6.3 14.1l6.6 4.8C14.7 15.1 19 12 24 12c3 0 5.7 1.1 7.8 3l5.7-5.7C34 5.7 29.3 4 24 4 16.3 4 9.7 8.3 6.3 14.1z"/>
            <path fill="#4CAF50" d="M24 44c5.2 0 10-2 13.6-5.2l-6.3-5.2c-2.1 1.5-4.7 2.4-7.3 2.4-5.3 0-9.7-3.4-11.3-8l-6.5 5C9.5 39.6 16.2 44 24 44z"/>
            <path fill="#1976D2" d="M43.6 20.5H42V20H24v8h11.3c-.8 2.3-2.3 4.2-4.3 5.6l6.3 5.2C41.5 35.4 44 30.1 44 24c0-1.3-.1-2.3-.4-3.5z"/>
        </svg>
    );
}

export function AppleIcon({ className = "h-5 w-5 fill-current" }) {
    return (
        <svg viewBox="0 0 814 1000" className={className} aria-hidden="true">
            <path d="M788.1 340.9c-5.8 4.5-108.2 62.2-108.2 190.5 0 148.4 130.3 200.9 134.2 202.2-.6 3.2-20.7 71.9-68.7 141.9-42.8 61.6-87.5 123.1-155.5 123.1s-85.5-39.5-164-39.5c-76 0-103.7 40.8-165.9 40.8s-105-37.5-159.5-113.2C115.9 802.2 90.9 700.1 90.9 602.1c0-161.8 105.7-247.2 209.2-247.2 55.1 0 100.9 36.4 140.5 36.4 37.9 0 103.5-38.5 170.5-38.5 26.7 0 130.1 2.5 194.7 104.2zm-158.5-155.1c29.8-35.3 50.7-84.5 50.7-133.7 0-6.8-.6-13.7-1.9-19.5-47.6 1.9-104.1 32.2-138.5 73.6-28.7 32.5-55.1 84.5-55.1 134.4 0 7.5 1.3 15 1.9 17.5 3.1.6 8.1 1.3 13.1 1.3 42.8 0 96.7-28.9 129.8-73.6z" />
        </svg>
    );
}

export function FieldStyles() {
    return (
        <style>{`
            .input-field {
                width: 100%;
                background: rgba(255,255,255,0.04);
                border: 1px solid rgba(255,255,255,0.08);
                color: #f8f8f8;
                padding: 16px 16px;
                border-radius: 16px;
                font-size: 16px;
                outline: none;
                transition: border-color .15s, box-shadow .15s, background .15s;
            }
            .input-field:focus {
                border-color: rgba(245,158,11,0.6);
                box-shadow: 0 0 0 4px rgba(245,158,11,0.12);
                background: rgba(255,255,255,0.06);
            }
        `}</style>
    );
}
