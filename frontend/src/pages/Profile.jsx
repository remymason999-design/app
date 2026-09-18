import { useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { LogOut, Settings, Tv2, Tag, Eye, TrendingUp, HelpCircle, Shield, ChevronDown, Lock, Download, Camera, Trash2, Sparkles, ChevronRight } from "lucide-react";
import { apiGet, apiPut, apiPost, apiDelete, formatApiError } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { toast } from "sonner";
import { motion, AnimatePresence } from "framer-motion";
import Tutorial, { resetTutorial } from "@/components/Tutorial";
import AccountMenu from "@/components/AccountMenu";
import { ProviderLogo } from "@/components/ProviderLogo";
import { deriveTasteRows, onboardingAffinityDecay } from "@/lib/taste";
import { PLUS_DEFAULT_CONFIG, fetchPlusConfig, fetchPlusInterest, trackPlusEvent } from "@/lib/plus";
import { capture, EVENTS } from "@/lib/analytics";
import { deleteAccountWithAnalytics } from "@/lib/analytics-flow";

const GENDER_OPTIONS = [
    { value: "male", label: "Male" },
    { value: "female", label: "Female" },
    { value: "nonbinary", label: "Non-binary" },
    { value: "prefer_not_to_say", label: "Prefer not to say" },
];

export default function Profile() {
    const { user, setUser, logout } = useAuth();
    const navigate = useNavigate();
    const [services, setServices] = useState([]);
    const [genres, setGenres] = useState([]);
    const [watchedCount, setWatchedCount] = useState(0);
    const [affiliate, setAffiliate] = useState({ total: 0, per_service: [] });
    const [tutorial, setTutorial] = useState(false);
    const [showPersonal, setShowPersonal] = useState(false);
    const [editDob, setEditDob] = useState("");
    const [editGender, setEditGender] = useState("");
    const [savingPersonal, setSavingPersonal] = useState(false);
    useEffect(() => { capture(EVENTS.PROVIDER_PREFERENCES_VIEWED, {}, { user, dedupeKey: "provider-preferences:viewed" }); // eslint-disable-line react-hooks/exhaustive-deps
    }, []);
    const [showPassword, setShowPassword] = useState(false);
    const [pwCurrent, setPwCurrent] = useState("");
    const [pwNew, setPwNew] = useState("");
    const [pwConfirm, setPwConfirm] = useState("");
    const [savingPw, setSavingPw] = useState(false);
    const [uploadingAvatar, setUploadingAvatar] = useState(false);
    const [avatarError, setAvatarError] = useState(false);
    const [plusConfig, setPlusConfig] = useState(PLUS_DEFAULT_CONFIG);
    const [plusInterest, setPlusInterest] = useState(null);
    const plusCardRef = useRef(null);
    const plusCardViewedRef = useRef(false);
    const fileInputRef = useRef(null);

    const onPickPhoto = () => fileInputRef.current?.click();

    const uploadAvatar = async (e) => {
        const file = e.target.files?.[0];
        e.target.value = "";
        if (!file) return;
        if (!file.type.startsWith("image/")) {
            toast.error("Please choose an image file.");
            return;
        }
        setUploadingAvatar(true);
        try {
            const form = new FormData();
            form.append("file", file);
            const res = await apiPost("/user/avatar", form);
            setUser({ ...user, picture: res.picture });
            setAvatarError(false);
            toast.success("Photo updated");
        } catch (err) {
            toast.error(formatApiError(err.response?.data?.detail) || "Couldn't upload photo");
        } finally {
            setUploadingAvatar(false);
        }
    };

    const removeAvatar = async () => {
        setUploadingAvatar(true);
        try {
            const res = await apiDelete("/user/avatar");
            setUser({ ...user, picture: res?.picture ?? null });
            setAvatarError(false);
            toast.success("Photo removed");
        } catch (err) {
            toast.error(formatApiError(err.response?.data?.detail) || "Couldn't remove photo");
        } finally {
            setUploadingAvatar(false);
        }
    };

    const changePassword = async (e) => {
        e?.preventDefault?.();
        if (pwNew.length < 8) {
            toast.error("New password must be at least 8 characters.");
            return;
        }
        if (pwNew !== pwConfirm) {
            toast.error("New passwords don't match.");
            return;
        }
        setSavingPw(true);
        try {
            await apiPost("/auth/change-password", { current_password: pwCurrent, new_password: pwNew });
            toast.success("Password updated");
            setPwCurrent(""); setPwNew(""); setPwConfirm("");
            setShowPassword(false);
        } catch (err) {
            toast.error(formatApiError(err.response?.data?.detail) || "Couldn't update password");
        } finally {
            setSavingPw(false);
        }
    };

    useEffect(() => {
        apiGet("/services").then(setServices);
        apiGet("/genres").then(setGenres);
        apiGet("/watched").then((m) => setWatchedCount(m.length));
        apiGet("/affiliate/me").then(setAffiliate).catch(() => {});
        fetchPlusConfig().then((config) => {
            if (config?.flags) setPlusConfig(config);
        }).catch(() => {});
        fetchPlusInterest().then(setPlusInterest).catch(() => {});
    }, [user?.user_id]);

    useEffect(() => {
        plusCardViewedRef.current = false;
    }, [user?.user_id]);

    useEffect(() => {
        const node = plusCardRef.current;
        if (!node || plusConfig.flags.plus_visible === false) return;
        if (!("IntersectionObserver" in window)) {
            return;
        }
        const observer = new IntersectionObserver(([entry]) => {
            if (!plusCardViewedRef.current && entry.isIntersecting && entry.intersectionRatio >= 0.5) {
                plusCardViewedRef.current = true;
                trackPlusEvent("plus_card_viewed", "profile", user?.user_id);
                observer.disconnect();
            }
        }, { threshold: [0.5] });
        observer.observe(node);
        return () => observer.disconnect();
    }, [plusConfig.flags.plus_visible, user?.user_id]);

    const openPlus = () => {
        trackPlusEvent("plus_card_clicked", "profile", user?.user_id);
        navigate("/watchsmart-plus?source=profile");
    };

    const toggleService = async (id) => {
        const prev = user;
        const next = user.subscriptions.includes(id)
            ? user.subscriptions.filter((s) => s !== id)
            : [...user.subscriptions, id];
        setUser({ ...user, subscriptions: next });
        try {
            const updated = await apiPut("/user/preferences", { services: next });
            setUser(updated);
            capture(next.includes(id) ? EVENTS.PROVIDER_ADDED : EVENTS.PROVIDER_REMOVED, {
                provider: id, provider_count: next.length, source: "profile",
            }, { user: updated, dedupeKey: `provider:${id}:${next.includes(id)}` });
        } catch (e) {
            setUser(prev);
            toast.error(formatApiError(e.response?.data?.detail) || "Couldn't update");
        }
    };

    const toggleGenre = async (g) => {
        const prev = user;
        const next = user.genres.includes(g)
            ? user.genres.filter((x) => x !== g)
            : [...user.genres, g];
        setUser({ ...user, genres: next });
        try {
            const updated = await apiPut("/user/preferences", { genres: next });
            setUser(updated);
        } catch (e) {
            setUser(prev);
            toast.error(formatApiError(e.response?.data?.detail) || "Couldn't update");
        }
    };

    const exportData = async () => {
        try {
            const data = await apiGet("/auth/export");
            const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
            const url = URL.createObjectURL(blob);
            const a = document.createElement("a");
            a.href = url;
            a.download = `watchsmart-data-${new Date().toISOString().slice(0, 10)}.json`;
            document.body.appendChild(a);
            a.click();
            a.remove();
            URL.revokeObjectURL(url);
            toast.success("Your data is downloading");
        } catch (e) {
            toast.error(formatApiError(e.response?.data?.detail) || "Couldn't export your data");
        }
    };

    const deleteAccount = async () => {
        const confirm1 = window.prompt('This will permanently delete your account, watchlist and all data. Type "DELETE" to confirm.');
        if (confirm1 !== "DELETE") return;
        try {
            await deleteAccountWithAnalytics(
                () => apiDelete("/auth/account"),
                { capture, reset: () => {}, EVENTS },
                user,
                logout
            );
            toast.success("Account deleted");
            navigate("/", { replace: true });
        } catch (e) {
            toast.error(formatApiError(e.response?.data?.detail) || "Couldn't delete account");
        }
    };

    const onLogout = async () => {
        await logout();
        navigate("/");
    };

    const openPersonal = () => {
        setEditDob(user.dob || "");
        setEditGender(user.gender || "");
        setShowPersonal(true);
    };

    const savePersonal = async () => {
        setSavingPersonal(true);
        try {
            const payload = {};
            if (editDob) payload.dob = editDob;
            if (editGender) payload.gender = editGender;
            const updated = await apiPut("/user/preferences", payload);
            setUser(updated);
            toast.success("Profile updated");
            setShowPersonal(false);
        } catch (e) {
            toast.error(formatApiError(e.response?.data?.detail) || "Couldn't save");
        } finally {
            setSavingPersonal(false);
        }
    };

    if (!user) return null;

    const tasteRows = deriveTasteRows({
        genreWeights: user.genre_weights,
        onboardingGenreWeights: user.onboarding_genre_weights,
        onboardingDecay: onboardingAffinityDecay(user.post_onboarding_interactions),
        selectedGenres: user.genres,
    });

    const replayTutorial = () => {
        resetTutorial();
        setTutorial(true);
    };

    return (
        <div className="min-h-screen px-5 pt-10 pb-28 max-w-md mx-auto" data-testid="profile-page">
            <Tutorial open={tutorial} onClose={() => setTutorial(false)} />
            <motion.div
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                className="flex items-center gap-4"
            >
                <button
                    type="button"
                    onClick={onPickPhoto}
                    disabled={uploadingAvatar}
                    data-testid="avatar-button"
                    aria-label="Change profile photo"
                    className="relative h-16 w-16 shrink-0 rounded-full overflow-hidden bg-amber grid place-items-center text-obsidian font-display text-2xl disabled:opacity-70"
                >
                    {user.picture && !avatarError ? (
                        <img
                            src={user.picture}
                            alt={user.name || "Profile"}
                            className="h-full w-full object-cover"
                            referrerPolicy="no-referrer"
                            draggable={false}
                            onError={() => setAvatarError(true)}
                        />
                    ) : (
                        user.name?.slice(0, 1)?.toUpperCase()
                    )}
                    <span className="absolute inset-x-0 bottom-0 h-6 bg-black/50 grid place-items-center">
                        <Camera className="w-3.5 h-3.5 text-white" strokeWidth={1.8} />
                    </span>
                </button>
                <input
                    ref={fileInputRef}
                    type="file"
                    accept="image/*"
                    onChange={uploadAvatar}
                    className="hidden"
                    data-testid="avatar-file-input"
                />
                <div className="flex-1 min-w-0">
                    <h1 className="font-heading text-2xl truncate">{user.name}</h1>
                    <p className="text-sm text-zinc-400 truncate">{user.email}</p>
                    <div className="flex items-center gap-3 mt-1.5">
                        <button
                            type="button"
                            onClick={onPickPhoto}
                            disabled={uploadingAvatar}
                            data-testid="avatar-change-btn"
                            className="text-xs text-amber hover:text-amber-600 disabled:opacity-60 transition-colors"
                        >
                            {uploadingAvatar ? "Saving…" : "Change photo"}
                        </button>
                        {user.picture && (
                            <button
                                type="button"
                                onClick={removeAvatar}
                                disabled={uploadingAvatar}
                                data-testid="avatar-remove-btn"
                                className="text-xs text-zinc-500 hover:text-red-400 disabled:opacity-60 transition-colors inline-flex items-center gap-1"
                            >
                                <Trash2 className="w-3 h-3" /> Remove
                            </button>
                        )}
                    </div>
                </div>
                <AccountMenu />
            </motion.div>

            <div className="grid grid-cols-3 gap-3 mt-6" data-testid="profile-stats">
                <Stat label="Saved" value={user.saved?.length || 0} icon={Tag} />
                <Stat label="Watched" value={watchedCount} icon={Eye} />
                <Stat label="Services" value={user.subscriptions?.length || 0} icon={Tv2} />
            </div>

            <Section title="What we’ve learned about you">
                <div className="glass rounded-2xl p-5" data-testid="learning-card">
                    {tasteRows.length === 0 ? (
                        <p className="text-sm text-zinc-400 leading-relaxed">
                            Choose a few genres or make a deliberate taste choice to start shaping your picks.
                        </p>
                    ) : (
                        <>
                            <p className="text-xs uppercase tracking-wider text-zinc-500 mb-3">YOUR TASTE SO FAR</p>
                            <ul className="space-y-2">
                                {tasteRows.map(({ genre, barPercent, strength }) => {
                                    return (
                                        <li key={genre} className="flex items-center gap-3" data-testid={`learned-${genre}`}>
                                            <span className="font-heading text-sm w-24 shrink-0">{genre}</span>
                                            <div className="flex-1 h-1.5 rounded-full bg-white/8 overflow-hidden">
                                                <div className="h-full bg-amber" style={{ width: `${barPercent}%` }} />
                                            </div>
                                            <span className="text-[11px] text-zinc-500 w-24 text-right">{strength}</span>
                                        </li>
                                    );
                                })}
                            </ul>
                        </>
                    )}
                </div>
            </Section>

            {plusConfig.flags.plus_visible !== false && (
                <Section title="WatchSmart+">
                    <button
                        ref={plusCardRef}
                        type="button"
                        onClick={openPlus}
                        className="w-full text-left rounded-2xl border border-amber/30 bg-gradient-to-br from-amber/15 via-white/[0.04] to-transparent p-5 hover:border-amber/50 transition-colors"
                        data-testid="plus-profile-card"
                    >
                        <div className="flex items-start gap-3">
                            <div className="h-10 w-10 rounded-xl bg-amber grid place-items-center text-obsidian shrink-0">
                                <Sparkles className="w-5 h-5" />
                            </div>
                            <div className="flex-1">
                                <div className="flex items-center gap-2">
                                    <span className="font-heading text-base">WatchSmart+</span>
                                    <span className="text-[10px] uppercase tracking-wider text-amber border border-amber/30 rounded-full px-2 py-0.5">COMING SOON</span>
                                </div>
                                <p className="text-sm text-zinc-400 mt-2 leading-relaxed">More ways to find what you love, watch together and get more from your streaming subscriptions.</p>
                                {plusInterest?.interested && (
                                    <p className="text-xs text-emerald-300 mt-2">You're on the list.</p>
                                )}
                            </div>
                            <ChevronRight className="w-4 h-4 text-zinc-500 mt-1 shrink-0" />
                        </div>
                    </button>
                </Section>
            )}

            <Section title="Streaming services">
                <div className="grid grid-cols-2 gap-2">
                    {services.map((s) => {
                        const on = user.subscriptions.includes(s.id);
                        return (
                            <button
                                key={s.id}
                                onClick={() => toggleService(s.id)}
                                data-testid={`profile-service-${s.id}`}
                                className={`flex items-center gap-2 p-3 rounded-xl border transition-colors text-left ${
                                    on ? "border-amber bg-amber/10" : "border-white/10 bg-white/[0.03]"
                                }`}
                            >
                                <ProviderLogo sid={s.id} size={28} shape="rounded-lg" />
                                <div>
                                    <div className="text-sm font-medium">{s.name}</div>
                                    <div className="text-[10px] text-zinc-500">£{s.price_monthly}/mo</div>
                                </div>
                            </button>
                        );
                    })}
                </div>
            </Section>

            <Section title="Favorite genres">
                <div className="flex flex-wrap gap-2">
                    {genres.map((g) => {
                        const on = user.genres.includes(g);
                        return (
                            <button
                                key={g}
                                onClick={() => toggleGenre(g)}
                                data-testid={`profile-genre-${g}`}
                                className={`px-3.5 py-2 rounded-full text-sm border ${
                                    on ? "bg-amber text-obsidian border-amber" : "border-white/10 text-zinc-300"
                                }`}
                            >
                                {g}
                            </button>
                        );
                    })}
                </div>
            </Section>

            <Section title="Personal details">
                <div className="glass rounded-2xl overflow-hidden">
                    <button
                        onClick={showPersonal ? () => setShowPersonal(false) : openPersonal}
                        data-testid="toggle-personal"
                        className="w-full flex items-center justify-between p-4 text-left hover:bg-white/5 transition-colors"
                    >
                        <div>
                            <div className="text-sm font-medium">Date of birth &amp; gender</div>
                            <div className="text-xs text-zinc-500 mt-0.5">
                                {user.dob || user.gender
                                    ? [user.dob, user.gender ? GENDER_OPTIONS.find((o) => o.value === user.gender)?.label : null].filter(Boolean).join(" · ")
                                    : "Not set"}
                            </div>
                        </div>
                        <ChevronDown className={`w-4 h-4 text-zinc-500 transition-transform ${showPersonal ? "rotate-180" : ""}`} />
                    </button>
                    <AnimatePresence>
                        {showPersonal && (
                            <motion.div
                                initial={{ height: 0, opacity: 0 }}
                                animate={{ height: "auto", opacity: 1 }}
                                exit={{ height: 0, opacity: 0 }}
                                transition={{ duration: 0.2 }}
                                className="overflow-hidden"
                            >
                                <div className="px-4 pb-4 space-y-4 border-t border-white/8 pt-4">
                                    <div>
                                        <label className="block text-xs uppercase tracking-[0.18em] text-zinc-500 mb-2">Date of birth</label>
                                        <input
                                            type="date"
                                            value={editDob}
                                            onChange={(e) => setEditDob(e.target.value)}
                                            max={new Date().toISOString().split("T")[0]}
                                            data-testid="profile-dob"
                                            style={{ colorScheme: "dark", width: "100%", background: "rgba(255,255,255,0.04)", border: "1px solid rgba(255,255,255,0.08)", color: "#f8f8f8", padding: "12px 14px", borderRadius: "12px", fontSize: "15px", outline: "none" }}
                                        />
                                    </div>
                                    <div>
                                        <div className="text-xs uppercase tracking-[0.18em] text-zinc-500 mb-2">Gender</div>
                                        <div className="grid grid-cols-2 gap-2">
                                            {GENDER_OPTIONS.map((opt) => (
                                                <button
                                                    key={opt.value}
                                                    type="button"
                                                    onClick={() => setEditGender((g) => g === opt.value ? "" : opt.value)}
                                                    data-testid={`profile-gender-${opt.value}`}
                                                    className={`py-2.5 px-3 rounded-xl border text-sm font-medium transition-colors text-center ${
                                                        editGender === opt.value
                                                            ? "border-amber bg-amber/10 text-amber"
                                                            : "border-white/10 bg-white/[0.03] text-zinc-300 hover:bg-white/[0.06]"
                                                    }`}
                                                >
                                                    {opt.label}
                                                </button>
                                            ))}
                                        </div>
                                    </div>
                                    <button
                                        onClick={savePersonal}
                                        disabled={savingPersonal}
                                        data-testid="save-personal"
                                        className="w-full bg-amber hover:bg-amber-600 disabled:opacity-60 text-obsidian font-heading text-sm py-3 rounded-xl transition-colors"
                                    >
                                        {savingPersonal ? "Saving…" : "Save"}
                                    </button>
                                </div>
                            </motion.div>
                        )}
                    </AnimatePresence>
                </div>
            </Section>

            <Section title="Supporting WatchSmart">
                <div className="glass rounded-2xl p-5" data-testid="affiliate-card">
                    <div className="flex items-start gap-3">
                        <div className="h-10 w-10 rounded-xl bg-amber/15 grid place-items-center shrink-0">
                            <TrendingUp className="h-5 w-5 text-amber" strokeWidth={1.6} />
                        </div>
                        <div className="flex-1">
                            <div className="font-heading text-base">
                                {affiliate.total} click{affiliate.total === 1 ? "" : "s"} to streaming partners
                            </div>
                            <p className="text-xs text-zinc-400 mt-1 leading-relaxed">
                                Every time you tap "Where to watch", we pass a referral tag. That helps keep WatchSmart free.
                            </p>
                            {affiliate.per_service.length > 0 && (
                                <ul className="mt-3 space-y-1.5">
                                    {affiliate.per_service.slice(0, 4).map((row) => (
                                        <li key={row.service_id} className="flex items-center justify-between text-xs text-zinc-400">
                                            <span>{row.service_name}</span>
                                            <span className="font-heading text-zinc-200">{row.count}</span>
                                        </li>
                                    ))}
                                </ul>
                            )}
                        </div>
                    </div>
                </div>
            </Section>

            <button
                onClick={replayTutorial}
                data-testid="replay-tutorial-btn"
                className="mt-8 w-full flex items-center justify-center gap-2 py-4 rounded-2xl border border-white/10 text-zinc-300 hover:bg-white/5"
            >
                <HelpCircle className="w-4 h-4" />
                Replay quick tour
            </button>

            {user.role === "admin" && (
                <Link
                    to="/admin"
                    data-testid="admin-link"
                    className="mt-3 w-full flex items-center justify-center gap-2 py-4 rounded-2xl border border-amber/40 bg-amber/10 text-amber hover:bg-amber/15 font-heading"
                >
                    <Shield className="w-4 h-4" />
                    Admin control room
                </Link>
            )}


            {user.auth_provider !== "google" && user.auth_provider !== "apple" && (
                <div className="mt-3" data-testid="password-section">
                    <button
                        onClick={() => setShowPassword((v) => !v)}
                        data-testid="change-password-toggle"
                        className="w-full flex items-center justify-center gap-2 py-4 rounded-2xl border border-white/10 text-zinc-300 hover:bg-white/5"
                        aria-expanded={showPassword}
                    >
                        <Lock className="w-4 h-4" />
                        {showPassword ? "Cancel password change" : "Change password"}
                    </button>
                    {showPassword && (
                        <form onSubmit={changePassword} className="glass rounded-2xl p-4 mt-2 space-y-3" data-testid="change-password-form">
                            <input
                                type="password"
                                autoComplete="current-password"
                                placeholder="Current password"
                                value={pwCurrent}
                                onChange={(e) => setPwCurrent(e.target.value)}
                                className="w-full bg-white/5 border border-white/10 rounded-xl px-3 py-3 text-sm focus:outline-none focus:border-amber"
                                required
                                data-testid="pw-current"
                            />
                            <input
                                type="password"
                                autoComplete="new-password"
                                placeholder="New password (min 8 chars)"
                                value={pwNew}
                                onChange={(e) => setPwNew(e.target.value)}
                                minLength={8}
                                className="w-full bg-white/5 border border-white/10 rounded-xl px-3 py-3 text-sm focus:outline-none focus:border-amber"
                                required
                                data-testid="pw-new"
                            />
                            <input
                                type="password"
                                autoComplete="new-password"
                                placeholder="Confirm new password"
                                value={pwConfirm}
                                onChange={(e) => setPwConfirm(e.target.value)}
                                minLength={8}
                                className="w-full bg-white/5 border border-white/10 rounded-xl px-3 py-3 text-sm focus:outline-none focus:border-amber"
                                required
                                data-testid="pw-confirm"
                            />
                            <button
                                type="submit"
                                disabled={savingPw}
                                data-testid="pw-submit"
                                className="w-full py-3 rounded-xl bg-amber text-obsidian font-heading disabled:opacity-50"
                            >
                                {savingPw ? "Updating…" : "Update password"}
                            </button>
                        </form>
                    )}
                </div>
            )}

            <button
                onClick={exportData}
                data-testid="export-data-btn"
                className="mt-3 w-full flex items-center justify-center gap-2 py-4 rounded-2xl border border-white/10 text-zinc-300 hover:bg-white/5"
            >
                <Download className="w-4 h-4" />
                Download my data
            </button>

            <button
                onClick={deleteAccount}
                data-testid="delete-account-btn"
                className="mt-3 w-full flex items-center justify-center gap-2 py-3 rounded-2xl text-xs text-zinc-500 hover:text-red-400 transition-colors"
            >
                Delete my account
            </button>

            <div className="mt-6 pt-6 border-t border-white/8">
                <button
                    onClick={onLogout}
                    data-testid="logout-btn"
                    className="w-full flex items-center justify-center gap-2 py-3 text-sm text-red-400 hover:text-red-300 transition-colors"
                >
                    <LogOut className="w-4 h-4" />
                    Sign out
                </button>
            </div>

            <div className="mt-8 pt-6 border-t border-white/8 flex flex-col items-center gap-2 text-xs text-zinc-500">
                <div className="flex items-center gap-4">
                    <Link to="/privacy" data-testid="link-privacy" className="hover:text-zinc-300 transition-colors">Privacy</Link>
                    <span className="text-zinc-700">·</span>
                    <Link to="/terms" data-testid="link-terms" className="hover:text-zinc-300 transition-colors">Terms</Link>
                </div>
                <a href="mailto:support@watchsmart.uk" data-testid="link-contact" className="hover:text-zinc-300 transition-colors">
                    support@watchsmart.uk
                </a>
            </div>
        </div>
    );
}

function Stat({ label, value, icon: Icon }) {
    return (
        <div className="glass rounded-2xl p-4 text-center">
            <Icon className="w-4 h-4 text-amber mx-auto mb-2" strokeWidth={1.6} />
            <div className="font-display text-2xl">{value}</div>
            <div className="text-[10px] uppercase tracking-wider text-zinc-500 mt-1">{label}</div>
        </div>
    );
}

function Section({ title, children }) {
    return (
        <section className="mt-8">
            <h2 className="font-heading text-base mb-3 flex items-center gap-2">
                <Settings className="w-3.5 h-3.5 text-zinc-500" /> {title}
            </h2>
            {children}
        </section>
    );
}
