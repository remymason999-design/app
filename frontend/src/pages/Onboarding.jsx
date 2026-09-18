import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { motion, AnimatePresence } from "framer-motion";
import {
    ThumbsUp, ThumbsDown, ChevronRight, Check, ArrowLeft,
    Film, Tv as TvIcon, Layers, Sparkles, X, SkipForward, Star,
} from "lucide-react";
import { apiGet, apiPost, apiPut, formatApiError } from "@/lib/api";
import { ProviderLogo } from "@/components/ProviderLogo";
import { useAuth } from "@/context/AuthContext";
import { toast } from "sonner";
import { capture, EVENTS } from "@/lib/analytics";

const MOODS = [
    { id: "funny", label: "Funny" },
    { id: "dark", label: "Dark" },
    { id: "easy-watch", label: "Easy watch" },
    { id: "thought-provoking", label: "Thought-provoking" },
    { id: "feel-good", label: "Feel-good" },
    { id: "edge-of-seat", label: "Edge of seat" },
    { id: "romantic", label: "Romantic" },
    { id: "epic", label: "Epic" },
];

const COUNTRY_LIST = [
    { code: "GB", name: "🇬🇧 UK" },
    { code: "US", name: "🇺🇸 US" },
    { code: "CA", name: "🇨🇦 Canada" },
    { code: "AU", name: "🇦🇺 Australia" },
    { code: "IE", name: "🇮🇪 Ireland" },
    { code: "IN", name: "🇮🇳 India" },
    { code: "DE", name: "🇩🇪 Germany" },
    { code: "FR", name: "🇫🇷 France" },
    { code: "ES", name: "🇪🇸 Spain" },
    { code: "IT", name: "🇮🇹 Italy" },
    { code: "NL", name: "🇳🇱 Netherlands" },
    { code: "BR", name: "🇧🇷 Brazil" },
    { code: "MX", name: "🇲🇽 Mexico" },
    { code: "JP", name: "🇯🇵 Japan" },
];

export default function Onboarding() {
    const navigate = useNavigate();
    const { user, setUser } = useAuth();
    const [step, _setStep] = useState(() => {
        const saved = parseInt(sessionStorage.getItem("ws_onboarding_step") || "1", 10);
        return saved >= 1 && saved <= 4 ? saved : 1;
    });
    const setStep = (s) => {
        _setStep((prev) => {
            const next = typeof s === "function" ? s(prev) : s;
            try { sessionStorage.setItem("ws_onboarding_step", String(next)); } catch {}
            return next;
        });
    };
    const [savingStep, setSavingStep] = useState(false);
    const [genres, setGenres] = useState([]);
    const [services, setServices] = useState([]);

    // Step 1
    const [pickedGenres, setPickedGenres] = useState(new Set(user?.genres || []));
    const [pickedMoods, setPickedMoods] = useState(new Set(user?.moods || []));

    // Step 2
    const [titles, setTitles] = useState([]);
    const [titleIdx, setTitleIdx] = useState(0);
    const [titlesLoading, setTitlesLoading] = useState(true);
    const [titlesError, setTitlesError] = useState(false);
    const [titlesRetry, setTitlesRetry] = useState(0);
    const [ratingBusy, setRatingBusy] = useState(false);
    const [ratedCount, setRatedCount] = useState(0);
    const [progress, setProgress] = useState(null);
    const [progressLoading, setProgressLoading] = useState(false);
    const [progressError, setProgressError] = useState(false);
    const [progressRetry, setProgressRetry] = useState(0);
    const [earlyPromptDismissed, setEarlyPromptDismissed] = useState(false);

    // Step 3
    const [excludeFamily, setExcludeFamily] = useState(
        (user?.excluded_categories || []).includes("family")
    );
    const [excludeAnime, setExcludeAnime] = useState(
        (user?.excluded_categories || []).includes("anime")
    );
    const [excludeBollywood, setExcludeBollywood] = useState(
        (user?.excluded_categories || []).includes("bollywood")
    );
    const [contentType, setContentType] = useState(user?.content_type || "both");
    const [excludedGenres, setExcludedGenres] = useState(new Set(user?.excluded_genres || []));
    const [country, setCountry] = useState(user?.country || "GB");

    // Step 4
    const [pickedServices, setPickedServices] = useState(new Set(user?.subscriptions || []));
    const [finishing, setFinishing] = useState(false);
    const onboardingStartedRef = useRef(false);
    const onboardingStartedAt = useMemo(() => Date.now(), []);

    useEffect(() => {
        if (onboardingStartedRef.current) return;
        onboardingStartedRef.current = true;
        capture(EVENTS.ONBOARDING_STARTED, {}, { user, dedupeKey: "onboarding:start" });
    // A flow is mounted once; auth identity changes must not restart it.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);

    useEffect(() => {
        Promise.all([apiGet("/genres"), apiGet("/services")])
            .then(([g, s]) => { setGenres(g); setServices(s); });
    }, []);

    // Progress is authoritative for resumed onboarding and completion gates.
    useEffect(() => {
        if (step !== 4) return;
        let active = true;
        setProgressLoading(true);
        setProgressError(false);
        apiGet("/onboarding/progress")
            .then((next) => {
                if (!active) return;
                setProgress(next);
                setRatedCount(Number.isFinite(Number(next?.interactions)) ? Number(next.interactions) : 0);
            })
            .catch(() => {
                if (active) setProgressError(true);
            })
            .finally(() => {
                if (active) setProgressLoading(false);
            });
        return () => { active = false; };
    }, [step, progressRetry]);

    // Lazy-load at most ten cards only when entering step 4. The API returns
    // the remaining deck for a resumed user.
    useEffect(() => {
        if (step === 4 && titles.length === 0) {
            setTitlesLoading(true);
            setTitlesError(false);
            apiGet("/onboarding/titles?limit=10")
                .then(setTitles)
                .catch(() => {
                    setTitlesError(true);
                    toast.error("Couldn't load titles");
                })
                .finally(() => setTitlesLoading(false));
        }
    }, [step, titles.length, titlesRetry]);

    const toggle = (set, setSet, val) => {
        const next = new Set(set);
        next.has(val) ? next.delete(val) : next.add(val);
        setSet(next);
    };

    // ---- Step 1 (Services) ---------------------------------------------
    const next1 = async () => {
        if (pickedServices.size > 0) {
            setSavingStep(true);
            try {
                const updated = await apiPut("/user/preferences", {
                    services: Array.from(pickedServices),
                });
                setUser(updated);
                capture(EVENTS.ONBOARDING_STEP_COMPLETED, { step: "services", selected_count: pickedServices.size }, { user });
            } catch (err) {
                toast.error(formatApiError(err.response?.data?.detail) || "Couldn't save your services. Please try again.");
                setSavingStep(false);
                return;
            }
            setSavingStep(false);
        }
        setStep(2);
    };

    // ---- Step 2 (Genres/Moods) -----------------------------------------
    const next2 = async () => {
        {
            setSavingStep(true);
            try {
                const updated = await apiPut("/user/preferences", {
                    genres: Array.from(pickedGenres),
                    moods: Array.from(pickedMoods),
                });
                setUser(updated);
                capture(EVENTS.ONBOARDING_STEP_COMPLETED, { step: "taste", genre_count: pickedGenres.size, mood_count: pickedMoods.size }, { user });
                setTitles([]);
                setTitleIdx(0);
            } catch (err) {
                toast.error(formatApiError(err.response?.data?.detail) || "Couldn't save your preferences. Please try again.");
                setSavingStep(false);
                return;
            }
            setSavingStep(false);
        }
        setStep(3);
    };

    // ---- Step 4 (Rating swipes) -----------------------------------------
    const rate = async (rating) => {
        if (ratingBusy || titleIdx >= titles.length) return;
        setRatingBusy(true);
        const movieId = titles[titleIdx].id;
        try {
            const r = await apiPost("/onboarding/rate", { movie_id: movieId, rating });
            if (r.user) setUser(r.user);
            capture(EVENTS.ONBOARDING_TITLE_FEEDBACK, { content_id: movieId, feedback: rating, media_type: titles[titleIdx]?.type || "movie" }, { user, dedupeKey: `onboarding:rating:${movieId}` });
            // Skip is neutral to taste, but is still a deliberate interaction
            // and counts toward the five-card minimum.
            setRatedCount((c) => c + 1);
            setTitleIdx((i) => i + 1);
            try {
                const nextProgress = await apiGet("/onboarding/progress");
                setProgress(nextProgress);
            } catch {
                // The interaction is saved; the next progress refresh will
                // restore the authoritative completion gate.
            }
        } catch (err) {
            toast.error(formatApiError(err.response?.data?.detail) || "Couldn't save rating");
        } finally {
            setRatingBusy(false);
        }
    };

    // ---- Step 3 (Preferences) ------------------------------------------
    const next3 = async () => {
        const cats = [];
        if (excludeFamily) cats.push("family");
        if (excludeAnime) cats.push("anime");
        if (excludeBollywood) cats.push("bollywood");
        setSavingStep(true);
        try {
            const updated = await apiPut("/user/preferences", {
                excluded_categories: cats,
                excluded_genres: Array.from(excludedGenres),
                content_type: contentType,
                country,
            });
            setUser(updated);
            capture(EVENTS.ONBOARDING_STEP_COMPLETED, { step: "preferences", content_type: contentType, country }, { user });
        } catch (err) {
            toast.error(formatApiError(err.response?.data?.detail) || "Couldn't save your filters. Please try again.");
            setSavingStep(false);
            return;
        }
        setSavingStep(false);
        setStep(4);
    };

    // ---- Step 4 finish (Rating complete → /onboarding/complete) ----------
    const finish = async () => {
        const supplyExhausted = !titlesLoading && !titlesError && (titles.length === 0 || titleIdx >= titles.length);
        const allowed = Boolean(progress?.can_finish || progress?.is_complete || supplyExhausted);
        if (!allowed) return;
        setFinishing(true);
        try {
            const completed = await apiPost("/onboarding/complete");
            setUser(completed);
            capture(EVENTS.ONBOARDING_COMPLETED, {
                providers_selected: completed?.subscriptions?.length,
                genres_selected: completed?.genres?.length,
                titles_rated: ratedCount,
                duration_ms: Math.max(0, Date.now() - onboardingStartedAt),
            }, { user: completed });
            sessionStorage.removeItem("ws_onboarding_step");
            toast.success("All set — handpicked just for you");
            navigate("/discover", { replace: true });
        } catch (err) {
            toast.error(formatApiError(err.response?.data?.detail) || "Couldn't save");
        } finally {
            setFinishing(false);
        }
    };

    const monthlyTotal = useMemo(() => services
        .filter((s) => pickedServices.has(s.id))
        .reduce((sum, s) => sum + s.price_monthly, 0), [services, pickedServices]);
    const supplyExhausted = !titlesLoading && !titlesError && (titles.length === 0 || titleIdx >= titles.length);
    const minimumInteractions = Number(progress?.minimum_interactions) || 5;
    const maximumInteractions = Number(progress?.maximum_interactions) || 10;
    const canFinish = !progressLoading && Boolean(
        progress?.can_finish || progress?.is_complete || supplyExhausted
    );

    return (
        <div className="min-h-screen px-6 pt-10 pb-32 max-w-md mx-auto" data-testid="onboarding-page">
            {/* Progress bar */}
            <ProgressBar step={step} />

            <AnimatePresence mode="wait">
                {step === 1 && (
                    <Step key="1" title="What do you pay for?" subtitle="We'll only surface titles you can stream right now. You can change this anytime.">
                        <div className="grid grid-cols-2 gap-3">
                            {services.map((s, i) => {
                                const on = pickedServices.has(s.id);
                                return (
                                    <motion.button
                                        key={s.id}
                                        initial={{ opacity: 0, y: 8 }}
                                        animate={{ opacity: 1, y: 0 }}
                                        transition={{ delay: i * 0.03 }}
                                        onClick={() => toggle(pickedServices, setPickedServices, s.id)}
                                        data-testid={`service-${s.id}`}
                                        className={`relative text-left rounded-2xl p-4 border transition-all ${
                                            on ? "border-amber bg-amber/10" : "border-white/10 bg-white/[0.03] hover:bg-white/[0.06]"
                                        }`}
                                    >
                                        <div className="mb-3">
                                            <ProviderLogo sid={s.id} size={36} shape="rounded-xl" />
                                        </div>
                                        <div className="font-heading text-base">{s.name}</div>
                                        <div className="text-xs text-zinc-400 mt-1">£{s.price_monthly.toFixed(2)}/mo</div>
                                        {on && (
                                            <div className="absolute top-3 right-3 w-6 h-6 rounded-full bg-amber flex items-center justify-center">
                                                <Check className="w-3.5 h-3.5 text-obsidian" strokeWidth={3} />
                                            </div>
                                        )}
                                    </motion.button>
                                );
                            })}
                        </div>
                    </Step>
                )}

                {step === 2 && (
                    <Step key="2" title="What do you love?" subtitle="Pick a few — we'll use these to kick-start your feed immediately.">
                        <SectionLabel>Genres</SectionLabel>
                        <ChipGroup
                            items={genres.map((g) => ({ id: g, label: g }))}
                            selected={pickedGenres}
                            onToggle={(g) => toggle(pickedGenres, setPickedGenres, g)}
                            testidPrefix="genre"
                        />
                        <SectionLabel className="mt-7">Mood</SectionLabel>
                        <ChipGroup
                            items={MOODS}
                            selected={pickedMoods}
                            onToggle={(m) => toggle(pickedMoods, setPickedMoods, m)}
                            testidPrefix="mood"
                        />
                    </Step>
                )}

                {step === 3 && (
                    <Step key="3" title="Filter the noise" subtitle="Hide anything you'll never watch. Applied across Discover, Search and Trending.">
                        <SectionLabel>Categories to hide</SectionLabel>
                        <div className="space-y-2">
                            <ToggleRow
                                label="Family & Kids"
                                description="Hides content aimed at children and families."
                                value={excludeFamily}
                                onChange={setExcludeFamily}
                                testid="toggle-family"
                            />
                            <ToggleRow
                                label="Anime"
                                description="Hides Japanese animation strictly — Pixar/Western animation stays."
                                value={excludeAnime}
                                onChange={setExcludeAnime}
                                testid="toggle-anime"
                            />
                            <ToggleRow
                                label="Bollywood"
                                description="Hides South-Asian cinema (Hindi, Telugu, Tamil, and more)."
                                value={excludeBollywood}
                                onChange={setExcludeBollywood}
                                testid="toggle-bollywood"
                            />
                        </div>

                        <SectionLabel className="mt-7">Content type</SectionLabel>
                        <Segmented
                            value={contentType}
                            onChange={setContentType}
                            options={[
                                { id: "both", label: "Both", icon: Layers },
                                { id: "movie", label: "Films", icon: Film },
                                { id: "tv", label: "TV", icon: TvIcon },
                            ]}
                        />

                        <SectionLabel className="mt-7">Genres to exclude (optional)</SectionLabel>
                        <ChipGroup
                            items={genres.map((g) => ({ id: g, label: g }))}
                            selected={excludedGenres}
                            onToggle={(g) => toggle(excludedGenres, setExcludedGenres, g)}
                            danger
                            testidPrefix="exclude-genre"
                        />

                        <SectionLabel className="mt-7">Country</SectionLabel>
                        <select
                            value={country}
                            onChange={(e) => setCountry(e.target.value)}
                            data-testid="onboarding-country"
                            className="w-full bg-white/5 border border-white/10 rounded-2xl p-3 text-sm focus:border-amber/60 outline-none"
                        >
                            {COUNTRY_LIST.map((c) => <option key={c.code} value={c.code}>{c.name}</option>)}
                        </select>
                    </Step>
                )}

                {step === 4 && (
                    <Step key="4" title="Quick taste check" subtitle="Up to 10 titles selected for your genres. Each deliberate tap trains your feed instantly.">
                        <RateDeck
                            titles={titles}
                            idx={titleIdx}
                            loading={titlesLoading}
                            titlesError={titlesError}
                            onRetryTitles={() => setTitlesRetry((count) => count + 1)}
                            onRate={rate}
                            ratedCount={ratedCount}
                            ratingBusy={ratingBusy}
                            progressLoading={progressLoading}
                            progressError={progressError}
                            onRetryProgress={() => setProgressRetry((count) => count + 1)}
                            canFinish={canFinish}
                            maximumInteractions={maximumInteractions}
                            onFinish={finish}
                            onContinue={() => setEarlyPromptDismissed(true)}
                            earlyPromptDismissed={earlyPromptDismissed}
                        />
                    </Step>
                )}
            </AnimatePresence>

            <BottomBar
                step={step}
                onBack={() => setStep((s) => Math.max(1, s - 1))}
                onSkip={
                    step === 1 ? () => setStep(2) :
                    step === 2 ? () => setStep(3) :
                    step === 3 ? () => setStep(4) :
                    null
                }
                onNext={
                    step === 1 ? next1 :
                    step === 2 ? next2 :
                    step === 3 ? next3 :
                    canFinish ? finish : null
                }
                primaryLabel={
                    step === 4
                        ? (finishing
                            ? "Finishing…"
                            : canFinish
                                ? "Finish onboarding"
                                : `${minimumInteractions} interactions minimum`)
                        : (savingStep ? "Saving…" : "Continue")
                }
                primaryDisabled={savingStep || (step === 4 && (finishing || !canFinish))}
                helper={
                    step === 4 ? (
                        <span data-testid="step4-helper">
                            {ratedCount}/{maximumInteractions} interactions
                            {canFinish && ratedCount < maximumInteractions ? " · finish whenever you’re ready" : ""}
                        </span>
                    ) : step === 1 && pickedServices.size > 0 ? (
                        <span>£{monthlyTotal.toFixed(2)}<span className="text-zinc-500">/mo</span></span>
                    ) : null
                }
            />
        </div>
    );
}

// =====================================================================
// Sub-components
// =====================================================================

function ProgressBar({ step }) {
    const steps = [
        { id: 1, label: "Stream" },
        { id: 2, label: "Taste" },
        { id: 3, label: "Filter" },
        { id: 4, label: "Rate" },
    ];
    return (
        <div className="mb-8" data-testid="onboarding-progress">
            <div className="flex items-center justify-between mb-2">
                <span className="text-[10px] uppercase tracking-[0.25em] text-amber">Step {step} of 4</span>
                <span className="text-[10px] uppercase tracking-wider text-zinc-500">{steps[step - 1].label}</span>
            </div>
            <div className="grid grid-cols-4 gap-1.5">
                {steps.map((s) => (
                    <div
                        key={s.id}
                        className={`h-1 rounded-full transition-all ${s.id <= step ? "bg-amber" : "bg-white/10"}`}
                    />
                ))}
            </div>
        </div>
    );
}

function Step({ title, subtitle, children }) {
    return (
        <motion.div
            initial={{ opacity: 0, x: 16 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: -16 }}
            transition={{ duration: 0.25 }}
        >
            <h1 className="font-display text-4xl leading-[1.05] mb-2">{title}</h1>
            <p className="text-zinc-400 text-sm mb-6">{subtitle}</p>
            {children}
        </motion.div>
    );
}

function SectionLabel({ children, className = "" }) {
    return <p className={`text-[10px] uppercase tracking-[0.22em] text-zinc-500 mb-3 ${className}`}>{children}</p>;
}

function ChipGroup({ items, selected, onToggle, testidPrefix, danger }) {
    return (
        <div className="flex flex-wrap gap-2">
            {items.map((item, i) => {
                const on = selected.has(item.id);
                const onClasses = danger
                    ? "bg-red-500/15 border-red-500/40 text-red-200"
                    : "bg-amber text-obsidian border-amber";
                return (
                    <motion.button
                        key={item.id}
                        initial={{ opacity: 0, scale: 0.95 }}
                        animate={{ opacity: 1, scale: 1 }}
                        transition={{ delay: i * 0.02 }}
                        onClick={() => onToggle(item.id)}
                        data-testid={`${testidPrefix}-${item.id}`}
                        className={`px-4 py-2.5 rounded-full text-sm font-medium border transition-colors ${
                            on ? onClasses : "border-white/12 text-zinc-300 hover:bg-white/5"
                        }`}
                    >
                        {danger && on && <X className="inline w-3 h-3 mr-1" />}
                        {item.label}
                    </motion.button>
                );
            })}
        </div>
    );
}

function ToggleRow({ label, description, value, onChange, testid }) {
    return (
        <button
            onClick={() => onChange(!value)}
            data-testid={testid}
            className={`w-full text-left rounded-2xl p-4 border transition-colors ${
                value ? "bg-amber/10 border-amber/40" : "bg-white/[0.03] border-white/10 hover:bg-white/[0.06]"
            }`}
        >
            <div className="flex items-center justify-between gap-3">
                <div className="min-w-0">
                    <div className="font-heading text-base">{label}</div>
                    <div className="text-xs text-zinc-500 mt-0.5">{description}</div>
                </div>
                <div className={`w-11 h-6 rounded-full p-0.5 transition-colors shrink-0 ${value ? "bg-amber" : "bg-white/15"}`}>
                    <div className={`w-5 h-5 rounded-full bg-white transition-transform ${value ? "translate-x-5" : ""}`} />
                </div>
            </div>
        </button>
    );
}

function Segmented({ value, onChange, options }) {
    return (
        <div className="grid grid-cols-3 gap-1.5 p-1 bg-white/4 rounded-2xl border border-white/5" data-testid="content-type-segmented">
            {options.map((o) => {
                const Icon = o.icon;
                const on = value === o.id;
                return (
                    <button
                        key={o.id}
                        onClick={() => onChange(o.id)}
                        data-testid={`content-type-${o.id}`}
                        className={`flex flex-col items-center justify-center gap-1 py-3 rounded-xl text-xs font-heading transition-colors ${
                            on ? "bg-amber text-obsidian" : "text-zinc-400 hover:text-zinc-100"
                        }`}
                    >
                        <Icon className="w-4 h-4" />
                        {o.label}
                    </button>
                );
            })}
        </div>
    );
}

function RateDeck({
    titles,
    idx,
    loading,
    titlesError,
    onRetryTitles,
    onRate,
    ratedCount,
    ratingBusy,
    progressLoading,
    progressError,
    onRetryProgress,
    canFinish,
    maximumInteractions,
    onFinish,
    onContinue,
    earlyPromptDismissed,
}) {
    if (progressLoading) {
        return (
            <div className="h-96 grid place-items-center">
                <div className="h-8 w-8 rounded-full border-2 border-amber border-t-transparent animate-spin" />
            </div>
        );
    }
    if (progressError) {
        return (
            <div className="glass rounded-2xl p-6 text-center">
                <p className="text-sm text-zinc-300 mb-4">Couldn&apos;t resume your taste check.</p>
                <button
                    type="button"
                    onClick={onRetryProgress}
                    className="border border-white/15 rounded-xl px-4 py-2 text-sm text-zinc-200 hover:bg-white/5"
                    data-testid="retry-onboarding-progress"
                >
                    Try again
                </button>
            </div>
        );
    }
    if (loading) {
        return (
            <div className="h-96 grid place-items-center">
                <div className="h-8 w-8 rounded-full border-2 border-amber border-t-transparent animate-spin" />
            </div>
        );
    }
    if (titlesError) {
        return (
            <div className="glass rounded-2xl p-6 text-center">
                <p className="text-sm text-zinc-300 mb-4">Couldn&apos;t load titles right now.</p>
                <button
                    type="button"
                    onClick={onRetryTitles}
                    className="border border-white/15 rounded-xl px-4 py-2 text-sm text-zinc-200 hover:bg-white/5"
                    data-testid="retry-onboarding-titles"
                >
                    Try again
                </button>
            </div>
        );
    }
    if (!titles.length) {
        return (
            <div className="glass rounded-2xl p-6 text-center">
                <Sparkles className="w-5 h-5 text-amber mx-auto mb-2" />
                <p className="text-sm text-zinc-300">No titles to rate right now — let's keep going.</p>
            </div>
        );
    }
    if (idx >= titles.length) {
        return (
            <div className="glass rounded-3xl p-8 text-center" data-testid="rate-done">
                <Sparkles className="w-6 h-6 text-amber mx-auto mb-3" />
                <h3 className="font-heading text-xl mb-2">{ratedCount} interactions in.</h3>
                <p className="text-sm text-zinc-400">Your feed is already learning. Finish now, or keep going for stronger personalisation.</p>
            </div>
        );
    }
    const m = titles[idx];
    const stack = titles.slice(idx, idx + 3);

    return (
        <div data-testid="rate-deck">
            <div className="relative h-[480px]" data-testid="rate-card-stack">
                <AnimatePresence mode="popLayout">
                    {stack.map((t, i) => (
                        <motion.div
                            key={t.id}
                            layout
                            initial={i === 0 ? { opacity: 0 } : false}
                            animate={{
                                opacity: 1,
                                scale: 1 - i * 0.04,
                                y: i * 8,
                                zIndex: 10 - i,
                            }}
                            exit={{ opacity: 0, x: -200, rotate: -8, transition: { duration: 0.25 } }}
                            transition={{ duration: 0.3, type: "spring", stiffness: 220, damping: 26 }}
                            className="absolute inset-0"
                        >
                            <RateCard movie={t} active={i === 0} />
                        </motion.div>
                    ))}
                </AnimatePresence>
            </div>

            <div className="flex items-center justify-center gap-4 mt-6" data-testid="rate-actions">
                <RateButton
                    icon={ThumbsDown}
                    onClick={() => onRate("dislike")}
                    disabled={ratingBusy}
                    color="red"
                    label="Not for me"
                    testid="rate-dislike"
                />
                <RateButton
                    icon={SkipForward}
                    onClick={() => onRate("skip")}
                    disabled={ratingBusy}
                    color="zinc"
                    small
                    label="Skip"
                    testid="rate-skip"
                />
                <RateButton
                    icon={ThumbsUp}
                    onClick={() => onRate("like")}
                    disabled={ratingBusy}
                    color="amber"
                    label="Love it"
                    testid="rate-like"
                />
            </div>

            <p className="text-center text-[11px] text-zinc-500 mt-3">
                {ratedCount} of {maximumInteractions} interactions · feed updates live
            </p>
            {canFinish && idx < titles.length && !earlyPromptDismissed && (
                <div className="mt-4 rounded-2xl border border-amber/25 bg-amber/5 px-4 py-3 flex items-center gap-3" data-testid="early-finish">
                    <p className="text-xs text-zinc-300 flex-1">
                        {ratedCount >= maximumInteractions
                            ? "You’ve reached the full taste check."
                            : `You’ve made ${ratedCount} deliberate choices — that’s enough to start.`}
                    </p>
                    <div className="shrink-0 flex items-center gap-3">
                        <button
                            type="button"
                            onClick={onContinue}
                            className="text-xs text-zinc-400 hover:text-zinc-100"
                            data-testid="continue-to-10"
                        >
                            Continue to 10
                        </button>
                        <button
                            type="button"
                            onClick={onFinish}
                            className="text-xs font-heading text-amber hover:text-amber-300"
                            data-testid="finish-early"
                        >
                            Finish now
                        </button>
                    </div>
                </div>
            )}
        </div>
    );
}

function RateCard({ movie, active }) {
    return (
        <div className="relative h-full rounded-3xl overflow-hidden ring-1 ring-white/8 bg-velvet">
            {movie.backdrop_url || movie.poster_url ? (
                <img
                    loading="lazy"
                    src={movie.poster_url}
                    alt={movie.title}
                    className="absolute inset-0 w-full h-full object-cover"
                />
            ) : null}
            <div className="absolute inset-0 bg-gradient-to-t from-black/95 via-black/40 to-transparent" />
            {active && (
                <div className="absolute top-4 left-4 flex items-center gap-2 px-3 py-1.5 rounded-full bg-black/50 backdrop-blur-sm border border-white/15">
                    <Star className="w-3 h-3 fill-amber text-amber" />
                    <span className="text-[11px] font-heading">{movie.rating ?? "—"}</span>
                    <span className="text-[10px] uppercase tracking-wider text-zinc-300">{movie.type === "tv" ? "TV" : "Film"}</span>
                </div>
            )}
            <div className="absolute bottom-0 left-0 right-0 p-5">
                <div className="text-[10px] uppercase tracking-[0.22em] text-amber mb-1">{(movie.genres || []).join(" · ")}</div>
                <h3 className="font-display text-2xl leading-tight mb-1">{movie.title}</h3>
                <p className="text-xs text-zinc-300 line-clamp-3">{movie.overview}</p>
            </div>
        </div>
    );
}

function RateButton({ icon: Icon, onClick, disabled, color, small, label, testid }) {
    const palette = {
        red: "bg-red-500/15 border-red-500/40 text-red-200 hover:bg-red-500/25",
        amber: "bg-amber text-obsidian border-amber hover:bg-amber-600 amber-glow",
        zinc: "bg-white/4 border-white/10 text-zinc-300 hover:bg-white/8",
    }[color];
    const size = small ? "w-12 h-12" : "w-14 h-14";
    return (
        <button
            onClick={onClick}
            disabled={disabled}
            data-testid={testid}
            aria-label={label}
            className={`${size} rounded-full grid place-items-center border transition-all disabled:opacity-50 active:scale-90 ${palette}`}
        >
            <Icon className={small ? "w-4 h-4" : "w-5 h-5"} strokeWidth={2} />
        </button>
    );
}

function BottomBar({ step, onBack, onSkip, onNext, primaryLabel, primaryDisabled, helper }) {
    return (
        <div
            className="fixed inset-x-0 bottom-0 glass-strong px-6 py-4 z-30"
            style={{ paddingBottom: "max(16px, env(safe-area-inset-bottom))" }}
            data-testid="onboarding-bottom-bar"
        >
            <div className="max-w-md mx-auto flex items-center gap-3">
                {step > 1 ? (
                    <button
                        onClick={onBack}
                        data-testid="onboarding-back"
                        aria-label="Back"
                        className="h-12 w-12 grid place-items-center rounded-2xl border border-white/10 text-zinc-300 hover:bg-white/5"
                    >
                        <ArrowLeft className="w-4 h-4" />
                    </button>
                ) : null}

                {helper && (
                    <div className="text-sm font-heading flex-1 truncate">{helper}</div>
                )}
                {!helper && <div className="flex-1" />}

                {onSkip && (
                    <button
                        onClick={onSkip}
                        data-testid="onboarding-skip"
                        className="text-sm text-zinc-400 hover:text-zinc-100 px-3"
                    >
                        Skip
                    </button>
                )}
                <button
                    onClick={onNext}
                    disabled={primaryDisabled}
                    data-testid="onboarding-next"
                    className="bg-amber hover:bg-amber-600 disabled:opacity-60 text-obsidian font-heading px-5 py-3.5 rounded-2xl amber-glow flex items-center gap-1.5"
                >
                    {primaryLabel} <ChevronRight className="w-4 h-4" />
                </button>
            </div>
        </div>
    );
}
