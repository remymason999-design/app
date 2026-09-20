/**
 * Discover — native swipe-card deck.
 *
 * Mirrors the web app (frontend/src/pages/Discover.jsx):
 *   - tab rail (For You / Movies / TV Shows) driving GET /discover,
 *   - backdrop-first swipe stack: right = save, left = skip, up = watched,
 *   - action row below the deck (Rewind / Skip / Watched / Save),
 *   - Rewind restores the previous card AND reverses the backend action,
 *   - background refill when the stack runs low + next-card image preloading.
 *
 * Action POSTs are fire-and-forget so the deck never waits on the network;
 * failures surface via a small inline notice and the rewind stack stays
 * consistent. Impression logging happens server-side during /discover — the
 * client only echoes each card's impression_id back on POST /user/action.
 */
import { Ionicons } from "@expo/vector-icons";
import { router, useFocusEffect } from "expo-router";
import * as Haptics from "expo-haptics";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { AppState, Image, Pressable, StyleSheet, Text, View } from "react-native";

import { ActionRow } from "@/components/discover/ActionRow";
import { CardSkeleton, EmptyState, ErrorState } from "@/components/discover/DiscoverStates";
import { InlineNotice } from "@/components/discover/InlineNotice";
import { SwipeCard, SwipeDir } from "@/components/discover/SwipeCard";
import { TabRail } from "@/components/discover/TabRail";
import { Toast } from "@/components/discover/Toast";
import { WatchedFeedbackSheet } from "@/components/discover/WatchedFeedbackSheet";
import { SCREEN_TOP_GAP } from "@/components/layout/ScreenContainer";
import { Colors } from "@/constants/colors";
import { useAuth } from "@/context/AuthContext";
import { getFriendlyMessage } from "@/lib/api";
import { analytics, EVENTS } from "@/lib/analytics";
import { afterSuccessfulMutation } from "@/lib/analytics-flow";
import {
  DiscoverCard,
  DiscoverTabId,
  PRELOAD_AHEAD,
  REFILL_LIMIT,
  REFILL_THRESHOLD,
  REVERSE_ACTION,
  StreamingService,
  SwipeAction,
  WatchedMeta,
  fetchDiscover,
  fetchServices,
  postAction,
} from "@/lib/discover-api";

const ANIM_MS = 230;

interface HistoryEntry {
  card: DiscoverCard;
  action: SwipeAction;
  /** Metadata captured for a "watched" action (sentiment / completed). */
  watchedMeta?: WatchedMeta;
  timeVisibleMs: number;
  interactionCount: number;
}

const DIR_TO_ACTION: Record<SwipeDir, SwipeAction> = {
  right: "save",
  left: "skip",
  up: "watched",
};

export default function Discover() {
  const { setUser, refresh, user } = useAuth();
  const userSubs = user?.subscriptions ?? [];
  const userRef = useRef(user);
  userRef.current = user;

  const [tab, setTab] = useState<DiscoverTabId>("for-you");
  const [stack, setStack] = useState<DiscoverCard[]>([]);
  const [services, setServices] = useState<StreamingService[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const [busy, setBusy] = useState(false); // an action animation is in flight
  const [screenFocused, setScreenFocused] = useState(false);
  const [appState, setAppState] = useState(AppState.currentState);
  // The card awaiting a "What did you think?" sentiment before we post + advance.
  const [pendingWatched, setPendingWatched] = useState<DiscoverCard | null>(null);

  const historyRef = useRef<HistoryEntry[]>([]);
  const [canRewind, setCanRewind] = useState(false);
  const refillingRef = useRef(false);
  const refillFailuresRef = useRef(0);
  const genRef = useRef(0); // invalidates in-flight fetches on tab change
  const preloadedRef = useRef<Set<string>>(new Set());
  const visibleSinceRef = useRef(new Map<string, number>());
  const impressionCountRef = useRef(0);
  const interactionCountRef = useRef(Number(user?.post_onboarding_interactions || 0));
  const activePresentationRef = useRef<string | null>(null);
  const presentationSequenceRef = useRef(0);
  useFocusEffect(useCallback(() => {
    setScreenFocused(true);
    return () => setScreenFocused(false);
  }, []));
  useEffect(() => {
    const subscription = AppState.addEventListener("change", setAppState);
    return () => subscription.remove();
  }, []);
  useEffect(() => {
    interactionCountRef.current = Math.max(
      interactionCountRef.current,
      Number(user?.post_onboarding_interactions || 0)
    );
  }, [user?.post_onboarding_interactions]);

  // ── Initial / tab-change load ─────────────────────────────────────────────
  const load = useCallback(
    async (tabId: DiscoverTabId) => {
      const startedAt = performance.now();
      const gen = ++genRef.current;
      refillFailuresRef.current = 0;
      historyRef.current = [];
      setCanRewind(false);
      setBusy(false); // clear any in-flight action state from the previous tab
      setPendingWatched(null); // dismiss a stale watched sheet on tab change
      setLoading(true);
      setError(null);
      try {
        const [cards, svcs] = await Promise.all([fetchDiscover(tabId), fetchServices()]);
        if (gen !== genRef.current) return;
        setStack(cards);
        setServices(svcs);
        analytics.capture(EVENTS.FEED_LOADED, {
          selected_tab: tabId,
          content_type: tabId === "for-you" ? "mixed" : tabId === "movies" ? "movie" : "tv",
          card_count: cards.length,
          source: "network",
          duration_ms: Math.round(performance.now() - startedAt),
        }, { user: userRef.current });
      } catch (e) {
        if (gen !== genRef.current) return;
        setError(getFriendlyMessage(e));
      } finally {
        if (gen === genRef.current) setLoading(false);
      }
    },
    []
  );

  useEffect(() => {
    load(tab);
  }, [tab, load]);

  // Only the active card is an impression. Fetching/refilling/prefetching never
  // reaches this effect.
  useEffect(() => {
    const card = stack[0];
    const visible = screenFocused && appState === "active" && card && !loading && !error;
    if (!visible || !card) {
      activePresentationRef.current = null;
      return;
    }
    const presentation = `${card.id}:${card.impression_id || ""}:${tab}`;
    if (activePresentationRef.current === presentation) return;
    activePresentationRef.current = presentation;
    presentationSequenceRef.current += 1;
    const now = Date.now();
    visibleSinceRef.current.set(card.id, now);
    impressionCountRef.current += 1;
    analytics.capture(EVENTS.RECOMMENDATION_IMPRESSION, {
      content_id: card.id,
      impression_id: card.impression_id,
      media_type: card.type,
      genres: card.genres,
      provider: card.available_on?.[0],
      feed_type: tab,
      recommendation_source: card._signals?.source,
      user_interaction_count: interactionCountRef.current,
      reason: card.reason || card._signals?.why_shown,
      session_impression_number: impressionCountRef.current,
      interaction_bucket: analytics.interactionBucket(interactionCountRef.current),
      visibility_started_at: new Date(now).toISOString(),
    }, { user: userRef.current, dedupeKey: `impression:${presentation}:${presentationSequenceRef.current}` });
  }, [stack[0]?.id, stack[0]?.impression_id, tab, loading, error, screenFocused, appState]);

  const servicesById = useMemo(
    () => Object.fromEntries(services.map((s) => [s.id, s])) as Record<string, StreamingService>,
    [services]
  );

  // ── Background refill when the stack runs low ─────────────────────────────
  useEffect(() => {
    if (loading || error || refillingRef.current) return;
    if (stack.length === 0 || stack.length >= REFILL_THRESHOLD) return;
    if (refillFailuresRef.current >= 3) return;
    refillingRef.current = true;
    const gen = genRef.current;
    (async () => {
      try {
        const more = await fetchDiscover(tab, REFILL_LIMIT);
        if (gen !== genRef.current) return;
        if (!more.length) {
          refillFailuresRef.current += 1;
          return;
        }
        setStack((prev) => {
          const ids = new Set(prev.map((m) => m.id));
          const fresh = more.filter((m) => !ids.has(m.id));
          if (!fresh.length) {
            refillFailuresRef.current += 1;
            return prev;
          }
          refillFailuresRef.current = 0;
          return [...prev, ...fresh];
        });
      } catch {
        refillFailuresRef.current += 1;
      } finally {
        if (gen === genRef.current) refillingRef.current = false;
        else refillingRef.current = false;
      }
    })();
  }, [stack.length, loading, error, tab]);

  // ── Preload the next few cards' images ────────────────────────────────────
  useEffect(() => {
    const upcoming = stack.slice(0, PRELOAD_AHEAD + 1);
    const set = preloadedRef.current;
    upcoming.forEach((m) => {
      for (const url of [m.backdrop_url, m.poster_url]) {
        if (url && !set.has(url)) {
          set.add(url);
          Image.prefetch(url).catch(() => {});
        }
      }
    });
    if (set.size > 400) preloadedRef.current = new Set(Array.from(set).slice(-200));
  }, [stack]);

  // ── Commit an action: fire the POST + advance the deck ────────────────────
  // Handles save / skip directly. "watched" is committed here too, but only
  // AFTER the feedback sheet resolves (see openWatched / commitWatched).
  const commitAction = useCallback(
    (top: DiscoverCard, action: SwipeAction, watchedMeta?: WatchedMeta) => {
      // Optimistic badge bump for saves (matches the web app).
      if (action === "save") {
        setUser?.((u) =>
          u ? { ...u, watchlist_unseen: (Number(u.watchlist_unseen) || 0) + 1 } : u
        );
      }

      // Fire-and-forget POST — the deck advances immediately.
      const timeVisible = Math.max(0, Date.now() - (visibleSinceRef.current.get(top.id) || Date.now()));
      const actionInteractionCount = interactionCountRef.current;
      afterSuccessfulMutation(
        () => postAction(top.id, action, top.impression_id, watchedMeta),
        () => {
        const eventName = action === "save" ? EVENTS.RECOMMENDATION_SAVED : action === "skip" ? EVENTS.RECOMMENDATION_SKIPPED : EVENTS.RECOMMENDATION_WATCHED;
        analytics.capture(eventName, {
          content_id: top.id,
          media_type: top.type,
          genres: top.genres,
          provider: top.available_on?.[0],
          recommendation_source: top._signals?.source,
          feed_type: tab,
          time_visible_ms: timeVisible,
          interaction_bucket: analytics.interactionBucket(actionInteractionCount),
        }, { dedupeKey: `discover:${top.id}:${action}:${top.impression_id || ""}`, user: userRef.current });
        interactionCountRef.current += 1;
        if (action === "watched" && watchedMeta) {
          analytics.capture(EVENTS.WATCHED_FEEDBACK_SUBMITTED, {
            content_id: top.id,
            impression_id: top.impression_id,
            media_type: top.type,
            feedback: watchedMeta.watched_sentiment || (watchedMeta.completed ? "watched" : "haven't_finished"),
            genres: top.genres,
            recommendation_source: top._signals?.source,
            user_interaction_count: actionInteractionCount,
            interaction_bucket: analytics.interactionBucket(actionInteractionCount),
          }, { dedupeKey: `watched-feedback:${top.id}:${watchedMeta.watched_sentiment || watchedMeta.completed}`, user: userRef.current });
        }
        analytics.markFirstDiscoverAction(userRef.current);
        }
      ).catch(() => {
        setNotice("Couldn't save that action — check your connection.");
        // Roll back the optimistic badge bump on failure.
        if (action === "save") {
          setUser?.((u) =>
            u ? { ...u, watchlist_unseen: Math.max(0, (Number(u.watchlist_unseen) || 0) - 1) } : u
          );
        }
      });

      // Advance the deck after the exit animation completes. Guard against a
      // tab change (which resets stack/history) firing this stale timeout.
      const gen = genRef.current;
      setTimeout(() => {
        if (gen !== genRef.current) return;
        historyRef.current = [
          ...historyRef.current,
          { card: top, action, watchedMeta, timeVisibleMs: timeVisible, interactionCount: actionInteractionCount },
        ].slice(-20);
        setCanRewind(true);
        setStack((s) => s.slice(1));
        setBusy(false);
      }, ANIM_MS);
    },
    [setUser, tab]
  );

  // ── Swipe / button action ─────────────────────────────────────────────────
  const doAction = useCallback(
    (dir: SwipeDir) => {
      if (busy) return;
      const top = stack[0];
      if (!top) return;
      const action = DIR_TO_ACTION[dir];

      // "Watched" no longer posts immediately — first ask how they felt.
      if (action === "watched") {
        Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Heavy).catch(() => {});
        setPendingWatched(top);
        return;
      }

      setBusy(true);
      Haptics.impactAsync(
        action === "save"
          ? Haptics.ImpactFeedbackStyle.Medium
          : Haptics.ImpactFeedbackStyle.Light
      ).catch(() => {});

      commitAction(top, action);
    },
    [busy, stack, commitAction]
  );

  // ── Watched feedback flow ─────────────────────────────────────────────────
  // The sheet resolves with a sentiment (or "haven't finished it"). We then
  // post "watched" with the metadata and advance exactly like other actions.
  const onWatchedSelect = useCallback(
    (meta: WatchedMeta) => {
      const top = pendingWatched;
      setPendingWatched(null);
      if (!top) return;
      if (busy) return;
      setBusy(true);
      Haptics.selectionAsync().catch(() => {});
      commitAction(top, "watched", meta);
      setToast("Nice — noted!");
    },
    [pendingWatched, busy, commitAction]
  );

  const onWatchedCancel = useCallback(() => {
    // Return to the card unchanged.
    setPendingWatched(null);
  }, []);

  // ── Rewind: restore previous card + reverse the backend action ────────────
  const doRewind = useCallback(() => {
    if (busy) return;
    const last = historyRef.current[historyRef.current.length - 1];
    if (!last) return;
    setBusy(true);
    Haptics.selectionAsync().catch(() => {});
    historyRef.current = historyRef.current.slice(0, -1);
    setCanRewind(historyRef.current.length > 0);
    setStack((s) => [last.card, ...s]);

    const reverse = REVERSE_ACTION[last.action];
    if (last.action === "save") {
      setUser?.((u) =>
        u ? { ...u, watchlist_unseen: Math.max(0, (Number(u.watchlist_unseen) || 0) - 1) } : u
      );
    }
    afterSuccessfulMutation(
      () => postAction(last.card.id, reverse, last.card.impression_id),
      () => {
      analytics.capture(EVENTS.RECOMMENDATION_REWOUND, {
        content_id: last.card.id,
        media_type: last.card.type,
        genres: last.card.genres,
        provider: last.card.available_on?.[0],
        recommendation_source: last.card._signals?.source,
        feed_type: tab,
        time_visible_ms: last.timeVisibleMs,
        interaction_bucket: analytics.interactionBucket(last.interactionCount),
      }, { dedupeKey: `reverse:${last.card.id}:${last.action}:${last.card.impression_id || ""}`, allowDuplicate: true, user: userRef.current });
      }
    ).catch(() => {
      setNotice("Couldn't rewind on the server — try again.");
    });
    const gen = genRef.current;
    setTimeout(() => {
      if (gen === genRef.current) setBusy(false);
    }, ANIM_MS);
  }, [busy, setUser, tab]);

  const openTitle = useCallback((card: DiscoverCard) => {
    router.push({ pathname: "/title/[id]", params: { id: card.id, type: card.type } });
  }, []);

  // ── Periodic user refresh (keep local user doc reasonably fresh) ──────────
  useEffect(() => {
    const t = setInterval(() => {
      refresh();
    }, 60_000);
    return () => clearInterval(t);
  }, [refresh]);

  // Render at most 2 cards: the interactive top card plus a single card behind
  // it (artwork only), fully covered by the top card so nothing bleeds out.
  const deck = stack.slice(0, 2);

  const deckBusy = busy || !!pendingWatched;

  return (
    <View style={[styles.container, { paddingTop: SCREEN_TOP_GAP }]}>
      <View style={styles.header}>
        <Text style={styles.h1}>Discover</Text>
        <Pressable
          onPress={() => router.push("/search")}
          hitSlop={8}
          style={styles.searchBtn}
          accessibilityRole="button"
          accessibilityLabel="Search"
          testID="open-search"
        >
          <Ionicons name="search" size={18} color={Colors.textSecondary} />
        </Pressable>
      </View>

      <View style={styles.tabWrap}>
        <TabRail active={tab} onChange={setTab} />
      </View>

      <View style={styles.deck}>
        {loading ? (
          <CardSkeleton />
        ) : error ? (
          <ErrorState message={error} onRetry={() => load(tab)} />
        ) : stack.length === 0 ? (
          <EmptyState onReload={() => load(tab)} />
        ) : (
          <>
            {deck
              .slice()
              .reverse()
              .map((card, idx, arr) => {
                const stackPos = arr.length - 1 - idx; // 2,1,0 → 0 is top
                const isTop = stackPos === 0;
                return (
                  <SwipeCard
                    key={card.id}
                    card={card}
                    servicesById={servicesById}
                    userSubs={userSubs}
                    isTop={isTop}
                    stackPos={stackPos}
                    disabled={deckBusy}
                    onSwipe={doAction}
                    onTap={() => openTitle(card)}
                  />
                );
              })}
            <InlineNotice message={notice} onHide={() => setNotice(null)} />
          </>
        )}
        <Toast message={toast} onHide={() => setToast(null)} />
      </View>

      {/* The tab bar occupies its own layout space (it is not absolutely
          positioned), so the screen must NOT pad by the tab-bar height —
          that double-counts it and leaves a dead gap. A small fixed gap is
          all that's needed; the deck above absorbs the reclaimed height. */}
      <View style={{ paddingBottom: 10 }}>
        <ActionRow
          onRewind={doRewind}
          onSkip={() => doAction("left")}
          onWatched={() => doAction("up")}
          onSave={() => doAction("right")}
          canRewind={canRewind}
          busy={deckBusy || loading || !!error || stack.length === 0}
        />
      </View>

      <WatchedFeedbackSheet
        visible={!!pendingWatched}
        title={pendingWatched?.title}
        onSelect={onWatchedSelect}
        onCancel={onWatchedCancel}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: Colors.obsidian, paddingHorizontal: 12 },
  header: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingHorizontal: 4,
    marginBottom: 8,
  },
  h1: { fontFamily: "Inter_800ExtraBold", fontSize: 24, color: Colors.text },
  searchBtn: {
    height: 34,
    width: 34,
    borderRadius: 17,
    borderWidth: 1,
    borderColor: Colors.border,
    backgroundColor: "rgba(255,255,255,0.03)",
    alignItems: "center",
    justifyContent: "center",
  },
  tabWrap: { marginBottom: 10 },
  deck: { flex: 1, minHeight: 0, position: "relative" },
});
