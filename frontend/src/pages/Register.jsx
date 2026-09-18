import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { motion, AnimatePresence } from "framer-motion";
import { ChevronDown, Eye, EyeOff } from "lucide-react";
import { apiGet, apiPost, formatApiError, setToken } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { toast } from "sonner";
import { Field, Divider, GoogleIcon, AppleIcon, FieldStyles } from "@/pages/Login";
import { capture, switchIdentity, EVENTS } from "@/lib/analytics";

const GENDER_OPTIONS = [
    { value: "male", label: "Male" },
    { value: "female", label: "Female" },
    { value: "nonbinary", label: "Non-binary" },
    { value: "prefer_not_to_say", label: "Prefer not to say" },
];

function pwStrength(pwd) {
    if (!pwd) return 0;
    let s = 0;
    if (pwd.length >= 8) s++;
    if (pwd.length >= 12) s++;
    if (/[A-Z]/.test(pwd)) s++;
    if (/[0-9]/.test(pwd)) s++;
    if (/[^A-Za-z0-9]/.test(pwd)) s++;
    return s;
}

const STRENGTH_META = [
    null,
    { label: "Very weak",   barCls: "bg-red-500",     textCls: "text-red-400" },
    { label: "Weak",        barCls: "bg-orange-500",  textCls: "text-orange-400" },
    { label: "Fair",        barCls: "bg-yellow-500",  textCls: "text-yellow-400" },
    { label: "Strong",      barCls: "bg-emerald-500", textCls: "text-emerald-400" },
    { label: "Very strong", barCls: "bg-emerald-400", textCls: "text-emerald-300" },
];

function PasswordField({ label, value, onChange, testId, showPassword, onToggleShow, enterKeyHint }) {
    const strength = pwStrength(value);
    const meta = STRENGTH_META[strength];
    return (
        <Field label={label}>
            <div className="relative">
                <input
                    type={showPassword ? "text" : "password"}
                    required
                    minLength={6}
                    autoComplete="new-password"
                    value={value}
                    onChange={onChange}
                    data-testid={testId}
                    className="input-field"
                    style={{ paddingRight: "3rem" }}
                    enterKeyHint={enterKeyHint || "next"}
                    inputMode="text"
                />
                <button
                    type="button"
                    tabIndex={-1}
                    onClick={onToggleShow}
                    className="absolute right-3 top-1/2 -translate-y-1/2 text-zinc-500 hover:text-zinc-300 transition-colors"
                    aria-label={showPassword ? "Hide password" : "Show password"}
                >
                    {showPassword ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                </button>
            </div>
            {value && meta && (
                <div className="mt-2 space-y-1">
                    <div className="flex gap-0.5">
                        {[1, 2, 3, 4, 5].map(i => (
                            <div
                                key={i}
                                className={`h-1 flex-1 rounded-full transition-all duration-300 ${strength >= i ? meta.barCls : "bg-white/10"}`}
                            />
                        ))}
                    </div>
                    <p className={`text-[10px] ${meta.textCls}`}>{meta.label}</p>
                </div>
            )}
        </Field>
    );
}

export default function Register() {
    const navigate = useNavigate();
    const { setUser } = useAuth();
    const [name, setName] = useState("");
    const [email, setEmail] = useState("");
    const [password, setPassword] = useState("");
    const [confirmPassword, setConfirmPassword] = useState("");
    const [showPwd, setShowPwd] = useState(false);
    const [showConfirm, setShowConfirm] = useState(false);
    const [dob, setDob] = useState("");
    const [gender, setGender] = useState("");
    const [showOptional, setShowOptional] = useState(false);
    const [acceptTerms, setAcceptTerms] = useState(false);
    const [loading, setLoading] = useState(false);

    const onSubmit = async (e) => {
        e.preventDefault();
        if (password !== confirmPassword) {
            toast.error("Passwords don't match");
            return;
        }
        if (!acceptTerms) {
            toast.error("Please accept the Terms & Privacy Policy to continue");
            return;
        }
        setLoading(true);
        try {
            const payload = { name, email, password, accept_terms: true };
            if (dob) payload.dob = dob;
            if (gender) payload.gender = gender;
            const data = await apiPost("/auth/register", payload);
            if (data.access_token) setToken(data.access_token);
            setUser(data.user);
            switchIdentity(data.user);
            capture(EVENTS.ACCOUNT_CREATED, { method: "password" }, { user: data.user });
            toast.success("Account created");
            navigate("/onboarding");
        } catch (err) {
            toast.error(formatApiError(err.response?.data?.detail) || "Registration failed");
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
                <Link to="/" className="text-xs uppercase tracking-[0.25em] text-zinc-500" data-testid="link-home">WatchSmart</Link>
                <h1 className="font-display text-4xl mt-6 mb-2">Create your account</h1>
                <p className="text-zinc-400 mb-8">Free forever. Cancel any time (yours and theirs).</p>

                <form onSubmit={onSubmit} className="space-y-4" data-testid="register-form">
                    <Field label="Name">
                        <input
                            type="text" required value={name} onChange={(e) => setName(e.target.value)}
                            data-testid="register-name" className="input-field"
                            enterKeyHint="next"
                        />
                    </Field>
                    <Field label="Email">
                        <input
                            type="email" required autoComplete="email" value={email}
                            onChange={(e) => setEmail(e.target.value)}
                            data-testid="register-email" className="input-field"
                            enterKeyHint="next"
                        />
                    </Field>

                    <PasswordField
                        label="Password"
                        value={password}
                        onChange={(e) => setPassword(e.target.value)}
                        testId="register-password"
                        showPassword={showPwd}
                        onToggleShow={() => setShowPwd(s => !s)}
                        enterKeyHint="next"
                    />

                    <PasswordField
                        label="Confirm password"
                        value={confirmPassword}
                        onChange={(e) => setConfirmPassword(e.target.value)}
                        testId="register-confirm-password"
                        showPassword={showConfirm}
                        onToggleShow={() => setShowConfirm(s => !s)}
                        enterKeyHint="done"
                    />

                    {/* Mismatch hint */}
                    {confirmPassword && password !== confirmPassword && (
                        <p className="text-[11px] text-red-400 -mt-2">Passwords don't match</p>
                    )}

                    {/* Optional profile details */}
                    <div>
                        <button
                            type="button"
                            onClick={() => setShowOptional((s) => !s)}
                            data-testid="toggle-optional"
                            className="flex items-center gap-2 text-xs uppercase tracking-[0.18em] text-zinc-500 hover:text-zinc-300 transition-colors mb-1"
                        >
                            <ChevronDown
                                className={`w-3.5 h-3.5 transition-transform ${showOptional ? "rotate-180" : ""}`}
                            />
                            Optional profile details
                        </button>
                        <AnimatePresence>
                            {showOptional && (
                                <motion.div
                                    initial={{ opacity: 0, height: 0 }}
                                    animate={{ opacity: 1, height: "auto" }}
                                    exit={{ opacity: 0, height: 0 }}
                                    transition={{ duration: 0.2 }}
                                    className="overflow-hidden"
                                >
                                    <div className="space-y-4 pt-3">
                                        <Field label="Date of birth">
                                            <input
                                                type="date"
                                                value={dob}
                                                onChange={(e) => setDob(e.target.value)}
                                                max={new Date().toISOString().split("T")[0]}
                                                data-testid="register-dob"
                                                className="input-field"
                                                style={{ colorScheme: "dark" }}
                                            />
                                        </Field>
                                        <div>
                                            <span className="block text-xs uppercase tracking-[0.18em] text-zinc-500 mb-2">Gender</span>
                                            <div className="grid grid-cols-2 gap-2">
                                                {GENDER_OPTIONS.map((opt) => (
                                                    <button
                                                        key={opt.value}
                                                        type="button"
                                                        onClick={() => setGender((g) => g === opt.value ? "" : opt.value)}
                                                        data-testid={`gender-${opt.value}`}
                                                        className={`py-3 px-3 rounded-xl border text-sm font-medium transition-colors text-center ${
                                                            gender === opt.value
                                                                ? "border-amber bg-amber/10 text-amber"
                                                                : "border-white/10 bg-white/[0.03] text-zinc-300 hover:bg-white/[0.06]"
                                                        }`}
                                                    >
                                                        {opt.label}
                                                    </button>
                                                ))}
                                            </div>
                                        </div>
                                    </div>
                                </motion.div>
                            )}
                        </AnimatePresence>
                    </div>

                    <label className="flex items-start gap-3 pt-1 cursor-pointer select-none" data-testid="terms-row">
                        <input
                            type="checkbox"
                            checked={acceptTerms}
                            onChange={(e) => setAcceptTerms(e.target.checked)}
                            data-testid="register-accept-terms"
                            className="mt-1 h-4 w-4 rounded border-white/20 bg-white/5 text-amber focus:ring-amber"
                        />
                        <span className="text-xs text-zinc-400 leading-relaxed">
                            I agree to the{" "}
                            <Link to="/terms" className="text-amber hover:underline">Terms of Service</Link>
                            {" "}and{" "}
                            <Link to="/privacy" className="text-amber hover:underline">Privacy Policy</Link>.
                        </span>
                    </label>

                    <button
                        type="submit"
                        disabled={loading || !acceptTerms}
                        data-testid="register-submit"
                        className="w-full bg-amber hover:bg-amber-600 disabled:opacity-60 text-obsidian font-heading text-base py-4 rounded-2xl transition-colors amber-glow"
                    >
                        {loading ? "Creating account…" : "Create account"}
                    </button>
                </form>

                <Divider>or</Divider>

                <div className="space-y-3">
                    <button
                        onClick={onGoogle}
                        data-testid="register-google"
                        className="w-full glass rounded-2xl py-4 flex items-center justify-center gap-3 font-medium hover:bg-white/5 transition-colors"
                    >
                        <GoogleIcon />
                        <span>Continue with Google</span>
                    </button>
                    <button
                        onClick={onApple}
                        data-testid="register-apple"
                        className="w-full bg-white text-black rounded-2xl py-4 flex items-center justify-center gap-3 font-medium hover:bg-zinc-100 transition-colors"
                    >
                        <AppleIcon className="h-5 w-5 fill-black" />
                        <span>Continue with Apple</span>
                    </button>
                </div>

                <p className="text-center text-sm text-zinc-500 mt-8">
                    Already have an account?{" "}
                    <Link to="/login" className="text-amber hover:underline" data-testid="link-login">Sign in</Link>
                </p>
            </motion.div>
            <FieldStyles />
        </div>
    );
}
