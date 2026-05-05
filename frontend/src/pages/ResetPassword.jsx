import { useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { motion } from "framer-motion";
import { Eye, EyeOff, ArrowLeft } from "lucide-react";
import { apiPost, formatApiError } from "@/lib/api";
import { Field, FieldStyles } from "@/pages/Login";
import { toast } from "sonner";

export default function ResetPassword() {
    const [params] = useSearchParams();
    const navigate = useNavigate();
    const token = params.get("token") || "";
    const [password, setPassword] = useState("");
    const [confirm, setConfirm] = useState("");
    const [showPwd, setShowPwd] = useState(false);
    const [loading, setLoading] = useState(false);

    const invalidLink = !token;

    const submit = async (e) => {
        e.preventDefault();
        if (password.length < 6) {
            toast.error("Password must be at least 6 characters");
            return;
        }
        if (password !== confirm) {
            toast.error("Passwords don't match");
            return;
        }
        setLoading(true);
        try {
            await apiPost("/auth/reset-password", { token, new_password: password });
            toast.success("Password updated — sign in with your new password");
            navigate("/login");
        } catch (err) {
            toast.error(formatApiError(err.response?.data?.detail) || "Reset failed");
        } finally {
            setLoading(false);
        }
    };

    return (
        <div className="min-h-screen px-6 py-12 max-w-md mx-auto" data-testid="reset-page">
            <Link to="/login" className="inline-flex items-center gap-2 text-xs uppercase tracking-[0.22em] text-zinc-500 mb-8">
                <ArrowLeft className="w-3 h-3" /> Back to sign in
            </Link>
            <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.4 }}>
                <h1 className="font-display text-4xl mb-2">Set new password</h1>
                <p className="text-zinc-400 mb-8 text-sm">
                    Choose something memorable — we'll log you straight in.
                </p>

                {invalidLink ? (
                    <div className="glass rounded-2xl p-5">
                        <p className="text-sm text-zinc-300 mb-3">This reset link is missing or malformed.</p>
                        <Link to="/forgot-password" className="text-amber text-sm hover:underline">Request a new link →</Link>
                    </div>
                ) : (
                    <form onSubmit={submit} className="space-y-4" data-testid="reset-form">
                        <Field label="New password">
                            <div className="relative">
                                <input
                                    type={showPwd ? "text" : "password"}
                                    required
                                    minLength={6}
                                    autoComplete="new-password"
                                    value={password}
                                    onChange={(e) => setPassword(e.target.value)}
                                    className="input-field pr-12"
                                    data-testid="reset-password"
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
                        <Field label="Confirm">
                            <input
                                type={showPwd ? "text" : "password"}
                                required
                                minLength={6}
                                value={confirm}
                                onChange={(e) => setConfirm(e.target.value)}
                                className="input-field"
                                data-testid="reset-confirm"
                            />
                        </Field>
                        <button
                            type="submit"
                            disabled={loading}
                            className="w-full bg-amber hover:bg-amber-600 disabled:opacity-60 text-obsidian font-heading text-base py-4 rounded-2xl transition-colors amber-glow"
                            data-testid="reset-submit"
                        >
                            {loading ? "Updating…" : "Update password"}
                        </button>
                    </form>
                )}
            </motion.div>
            <FieldStyles />
        </div>
    );
}
