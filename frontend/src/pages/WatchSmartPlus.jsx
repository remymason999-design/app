import { useEffect, useMemo, useState } from "react";
import { ArrowLeft, Bell, Check, ChevronRight, CircleAlert, Sparkles } from "lucide-react";
import { useLocation, useNavigate } from "react-router-dom";
import { toast } from "sonner";

import { apiGet, formatApiError } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import {
    PLUS_BENEFITS,
    PLUS_DEFAULT_CONFIG,
    addPlusInterest,
    fetchPlusConfig,
    fetchPlusInterest,
    removePlusInterest,
    sanitizePlusSource,
    trackPlusEvent,
} from "@/lib/plus";
import { plusInterestView, reconcilePlusInterest } from "@/lib/plus-state";

const CONFIRMATION = "You're on the list. We'll let you know when WatchSmart+ is ready.";

export default function WatchSmartPlus() {
    const { user } = useAuth();
    const navigate = useNavigate();
    const location = useLocation();
    const source = useMemo(() => {
        const value = new URLSearchParams(location.search).get("source");
        return sanitizePlusSource(value || "profile");
    }, [location.search]);
    const [config, setConfig] = useState(PLUS_DEFAULT_CONFIG);
    const [configLoading, setConfigLoading] = useState(true);
    const [configError, setConfigError] = useState(false);
    const [interest, setInterest] = useState(null);
    const [interestLoading, setInterestLoading] = useState(true);
    const [interestError, setInterestError] = useState(false);
    const [interestBusy, setInterestBusy] = useState(false);

    const loadConfig = async () => {
        setConfigLoading(true);
        setConfigError(false);
        try {
            const next = await fetchPlusConfig({ force: configError });
            setConfig(next?.flags ? next : PLUS_DEFAULT_CONFIG);
        } catch {
            setConfig(PLUS_DEFAULT_CONFIG);
            setConfigError(true);
        } finally {
            setConfigLoading(false);
        }
    };
    const loadInterest = async () => {
        setInterestLoading(true);
        setInterestError(false);
        try {
            setInterest(await fetchPlusInterest());
        } catch {
            setInterest(null);
            setInterestError(true);
        } finally {
            setInterestLoading(false);
        }
    };

    useEffect(() => {
        loadConfig();
        loadInterest();
        trackPlusEvent("plus_preview_viewed", source, user?.user_id);
        // A route mount is one preview visit; retries do not re-count it.
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [source, user?.user_id]);

    const enabled = interest?.enabled ?? config.flags.plus_interest_enabled;
    const interestView = plusInterestView({
        loading: interestLoading,
        error: interestError,
        interest,
        enabled,
    });
    const onInterest = async () => {
        if (interestBusy || interestLoading || !enabled) return;
        setInterestBusy(true);
        try {
            const result = await addPlusInterest(source);
            setInterest((current) => reconcilePlusInterest(current, true));
            if (result?.changed) toast.success(CONFIRMATION);
        } catch (error) {
            toast.error(formatApiError(error?.response?.data?.detail) || "Couldn't save your interest. Try again.");
        } finally {
            setInterestBusy(false);
        }
    };
    const undoInterest = async () => {
        if (interestBusy) return;
        setInterestBusy(true);
        try {
            await removePlusInterest();
            setInterest((current) => reconcilePlusInterest(current, false));
        } catch (error) {
            toast.error(formatApiError(error?.response?.data?.detail) || "Couldn't update your interest. Try again.");
        } finally {
            setInterestBusy(false);
        }
    };

    if (!configLoading && config.flags.plus_visible === false) {
        return (
            <main className="min-h-screen px-5 pt-6 pb-28 max-w-md mx-auto">
                <button onClick={() => navigate(-1)} className="h-11 w-11 rounded-full glass grid place-items-center" aria-label="Go back">
                    <ArrowLeft className="w-5 h-5" />
                </button>
                <div className="mt-16 text-center">
                    <CircleAlert className="mx-auto w-8 h-8 text-zinc-500" />
                    <h1 className="font-display text-3xl mt-4">WatchSmart+ is unavailable</h1>
                    <p className="text-sm text-zinc-400 mt-3">Please try again later.</p>
                    <button onClick={loadConfig} className="mt-6 text-amber text-sm font-heading">Try again</button>
                </div>
            </main>
        );
    }

    return (
        <main className="min-h-screen px-5 pt-6 pb-28 max-w-md mx-auto" data-testid="plus-preview-page">
            <div className="flex items-center gap-3">
                <button onClick={() => navigate(-1)} className="h-11 w-11 rounded-full glass grid place-items-center" aria-label="Go back" data-testid="plus-back">
                    <ArrowLeft className="w-5 h-5" />
                </button>
                <span className="text-xs uppercase tracking-[0.2em] text-zinc-500">Preview</span>
            </div>

            <section className="mt-8 rounded-3xl border border-amber/30 bg-gradient-to-br from-amber/15 via-white/[0.04] to-transparent p-6" data-testid="plus-hero">
                <div className="flex items-center gap-3">
                    <div className="h-11 w-11 rounded-2xl bg-amber grid place-items-center text-obsidian">
                        <Sparkles className="w-5 h-5" />
                    </div>
                    <div>
                        <h1 className="font-display text-3xl leading-none">WatchSmart+</h1>
                        <p className="text-amber text-xs uppercase tracking-[0.18em] mt-2 font-heading">Coming Soon</p>
                    </div>
                </div>
                <p className="mt-6 text-zinc-300 leading-relaxed">We're building even more ways to make streaming smarter.</p>
            </section>

            {configError && (
                <div className="mt-4 flex items-start gap-3 rounded-2xl border border-amber/20 bg-amber/5 p-4 text-xs text-zinc-400">
                    <CircleAlert className="w-4 h-4 text-amber shrink-0 mt-0.5" />
                    <div className="flex-1">Some preview settings couldn't be refreshed.</div>
                    <button onClick={loadConfig} className="text-amber font-heading">Retry</button>
                </div>
            )}

            <section className="mt-8 space-y-3" aria-label="Planned WatchSmart+ benefits">
                {PLUS_BENEFITS.map(([heading, copy]) => (
                    <div key={heading} className="glass rounded-2xl p-4 flex items-start gap-3">
                        <div className="h-8 w-8 rounded-xl bg-amber/10 grid place-items-center shrink-0">
                            <ChevronRight className="w-4 h-4 text-amber" />
                        </div>
                        <div>
                            <h2 className="font-heading text-sm tracking-wide">{heading}</h2>
                            <p className="text-sm text-zinc-400 leading-relaxed mt-1">{copy}</p>
                        </div>
                    </div>
                ))}
            </section>

            <section className="mt-10 glass rounded-3xl p-5" data-testid="plus-interest">
                <h2 className="font-heading text-lg">Interested in WatchSmart+?</h2>
                {interestView === "error" ? (
                    <div className="mt-3">
                        <p className="text-sm text-zinc-400">We couldn't check your current interest status.</p>
                        <button onClick={loadInterest} className="mt-3 text-sm text-amber font-heading">Retry</button>
                    </div>
                ) : interestView === "interested" ? (
                    <div className="mt-4">
                        <p className="flex items-start gap-2 text-sm text-emerald-300 leading-relaxed">
                            <Check className="w-4 h-4 mt-0.5 shrink-0" /> {CONFIRMATION}
                        </p>
                        <button onClick={undoInterest} disabled={interestBusy} className="mt-5 text-sm text-zinc-400 underline disabled:opacity-50" data-testid="plus-interest-remove">
                            {interestBusy ? "Updating…" : "Remove me from the list"}
                        </button>
                    </div>
                ) : interestView === "disabled" ? (
                    <p className="mt-3 text-sm text-zinc-400">Interest registration is not available right now.</p>
                ) : (
                    <>
                        <p className="mt-2 text-sm text-zinc-400">We'll only use this to let you know when the preview becomes available.</p>
                        <button
                            onClick={onInterest}
                            disabled={interestBusy || interestLoading}
                            className="mt-5 w-full bg-amber text-obsidian font-heading rounded-2xl py-3.5 flex items-center justify-center gap-2 disabled:opacity-50"
                            data-testid="plus-interest-btn"
                        >
                            {interestBusy ? "Saving…" : <><Bell className="w-4 h-4" /> Notify me when it launches</>}
                        </button>
                    </>
                )}
            </section>
        </main>
    );
}