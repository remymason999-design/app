import { useState } from "react";
import { Link } from "react-router-dom";
import { motion } from "framer-motion";
import { Copy, Check, ArrowLeft } from "lucide-react";
import { apiPost, formatApiError } from "@/lib/api";
import { Field, FieldStyles } from "@/pages/Login";
import { toast } from "sonner";

export default function ForgotPassword() {
    const [email, setEmail] = useState("");
    const [loading, setLoading] = useState(false);
    const [result, setResult] = useState(null);
    const [copied, setCopied] = useState(false);

    const submit = async (e) => {
        e.preventDefault();
        setLoading(true);
        try {
            const r = await apiPost("/auth/forgot-password", { email });
            setResult(r);
        } catch (err) {
            toast.error(formatApiError(err.response?.data?.detail) || "Couldn't send reset link");
        } finally {
            setLoading(false);
        }
    };

    const copy = async () => {
        await navigator.clipboard.writeText(result.reset_url);
        setCopied(true);
        toast.success("Link copied");
        setTimeout(() => setCopied(false), 2000);
    };

    return (
        <div className="min-h-screen px-6 py-12 max-w-md mx-auto" data-testid="forgot-page">
            <Link to="/login" className="inline-flex items-center gap-2 text-xs uppercase tracking-[0.22em] text-zinc-500 mb-8" data-testid="forgot-back">
                <ArrowLeft className="w-3 h-3" /> Back to sign in
            </Link>
            <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.4 }}>
                <h1 className="font-display text-4xl mb-2">Reset password</h1>
                <p className="text-zinc-400 mb-8 text-sm">
                    Enter your email — we'll send you a one-hour reset link.
                </p>

                {!result ? (
                    <form onSubmit={submit} className="space-y-4" data-testid="forgot-form">
                        <Field label="Email">
                            <input
                                type="email"
                                required
                                autoComplete="email"
                                value={email}
                                onChange={(e) => setEmail(e.target.value)}
                                className="input-field"
                                data-testid="forgot-email"
                            />
                        </Field>
                        <button
                            type="submit"
                            disabled={loading}
                            className="w-full bg-amber hover:bg-amber-600 disabled:opacity-60 text-obsidian font-heading text-base py-4 rounded-2xl transition-colors amber-glow"
                            data-testid="forgot-submit"
                        >
                            {loading ? "Sending…" : "Send reset link"}
                        </button>
                    </form>
                ) : (
                    <div className="space-y-5" data-testid="forgot-result">
                        <div className="glass rounded-2xl p-5">
                            <div className="text-sm text-zinc-300 mb-3">{result.message}</div>
                            {!result.reset_url && (
                                <p className="text-xs text-emerald-400">
                                    If that email is registered, check your inbox — the link expires in 1 hour.
                                </p>
                            )}
                            {result.reset_url && (
                                <>
                                    <p className="text-[11px] uppercase tracking-wider text-zinc-500 mb-2">Your reset link (1 hour)</p>
                                    <div className="flex items-center gap-2 bg-black/30 rounded-xl p-3 border border-white/5">
                                        <code className="text-[11px] text-zinc-300 break-all flex-1" data-testid="reset-url">
                                            {result.reset_url}
                                        </code>
                                        <button
                                            onClick={copy}
                                            className="shrink-0 h-9 w-9 grid place-items-center rounded-lg bg-amber text-obsidian hover:bg-amber-600 transition-colors"
                                            data-testid="copy-reset-link"
                                            aria-label="Copy reset link"
                                        >
                                            {copied ? <Check className="w-4 h-4" /> : <Copy className="w-4 h-4" />}
                                        </button>
                                    </div>
                                    <p className="text-[11px] text-zinc-500 mt-3">
                                        Dev mode — the link is shown here for convenience. In production it's sent by email only.
                                    </p>
                                </>
                            )}
                        </div>
                        <Link
                            to="/login"
                            className="block text-center text-sm text-amber hover:underline"
                        >
                            Back to sign in
                        </Link>
                    </div>
                )}
            </motion.div>
            <FieldStyles />
        </div>
    );
}
