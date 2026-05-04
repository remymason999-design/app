import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { motion } from "framer-motion";
import { apiPost, formatApiError } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { toast } from "sonner";
import { Field, Divider, GoogleIcon, FieldStyles } from "@/pages/Login";

export default function Register() {
    const navigate = useNavigate();
    const { setUser } = useAuth();
    const [name, setName] = useState("");
    const [email, setEmail] = useState("");
    const [password, setPassword] = useState("");
    const [loading, setLoading] = useState(false);

    const onSubmit = async (e) => {
        e.preventDefault();
        setLoading(true);
        try {
            const data = await apiPost("/auth/register", { name, email, password });
            setUser(data.user);
            toast.success("Account created");
            navigate("/onboarding/services");
        } catch (err) {
            toast.error(formatApiError(err.response?.data?.detail) || "Registration failed");
        } finally {
            setLoading(false);
        }
    };

    const onGoogle = () => {
        // REMINDER: DO NOT HARDCODE THE URL, OR ADD ANY FALLBACKS OR REDIRECT URLS, THIS BREAKS THE AUTH
        const redirectUrl = window.location.origin + "/discover";
        window.location.href = `https://auth.emergentagent.com/?redirect=${encodeURIComponent(redirectUrl)}`;
    };

    return (
        <div className="min-h-screen px-6 py-12 max-w-md mx-auto flex flex-col">
            <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.4 }}>
                <Link to="/" className="text-xs uppercase tracking-[0.25em] text-zinc-500" data-testid="link-home">Reelm</Link>
                <h1 className="font-display text-4xl mt-6 mb-2">Create your account</h1>
                <p className="text-zinc-400 mb-8">Free forever. Cancel any time (yours and theirs).</p>

                <form onSubmit={onSubmit} className="space-y-4" data-testid="register-form">
                    <Field label="Name">
                        <input
                            type="text" required value={name} onChange={(e) => setName(e.target.value)}
                            data-testid="register-name" className="input-field"
                        />
                    </Field>
                    <Field label="Email">
                        <input
                            type="email" required autoComplete="email" value={email}
                            onChange={(e) => setEmail(e.target.value)}
                            data-testid="register-email" className="input-field"
                        />
                    </Field>
                    <Field label="Password">
                        <input
                            type="password" required minLength={6} autoComplete="new-password"
                            value={password} onChange={(e) => setPassword(e.target.value)}
                            data-testid="register-password" className="input-field"
                        />
                    </Field>
                    <button
                        type="submit"
                        disabled={loading}
                        data-testid="register-submit"
                        className="w-full bg-amber hover:bg-amber-600 disabled:opacity-60 text-obsidian font-heading text-base py-4 rounded-2xl transition-colors amber-glow"
                    >
                        {loading ? "Creating account…" : "Create account"}
                    </button>
                </form>

                <Divider>or</Divider>
                <button
                    onClick={onGoogle}
                    data-testid="register-google"
                    className="w-full glass rounded-2xl py-4 flex items-center justify-center gap-3 font-medium hover:bg-white/5 transition-colors"
                >
                    <GoogleIcon />
                    <span>Continue with Google</span>
                </button>

                <p className="text-center text-sm text-zinc-500 mt-8">
                    Already have an account?{" "}
                    <Link to="/login" className="text-amber hover:underline" data-testid="link-login">Sign in</Link>
                </p>
            </motion.div>
            <FieldStyles />
        </div>
    );
}
