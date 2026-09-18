import { Ionicons } from "@expo/vector-icons";
import { useQuery } from "@tanstack/react-query";
import * as Haptics from "expo-haptics";
import { LinearGradient } from "expo-linear-gradient";
import { Stack, router, useLocalSearchParams } from "expo-router";
import { useCallback, useEffect, useState } from "react";
import {
  ActivityIndicator,
  Dimensions,
  Image,
  Linking,
  Pressable,
  ScrollView,
  Share,
  StyleSheet,
  Text,
  View,
} from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { ProviderRow } from "@/components/title/ProviderRow";
import { SimilarRow } from "@/components/title/SimilarRow";
import { Colors } from "@/constants/colors";
import { useAuth } from "@/context/AuthContext";
import {
  ContentAction,
  MovieDetail,
  SimilarItem,
  engage,
  fetchMovie,
  fetchServices,
  fetchSimilar,
  formatRuntime,
  getCertification,
  postAction,
} from "@/lib/content-api";
import { WatchedSentiment, postWatchedFeedback } from "@/lib/discover-api";
import { analytics, EVENTS } from "@/lib/analytics";

const TMDB_URL = "https://www.themoviedb.org";
const { width: SCREEN_W } = Dimensions.get("window");
// Hero uses a ~16:10 crop (a touch taller than 16:9) so backdrops fill nicely
// while leaving room for the title block over the gradient.
const HERO_H = Math.round(SCREEN_W * (10 / 16));

// One TRUE smooth transparent → page-bg gradient at the hero's bottom
// (expo-linear-gradient renders a real gradient — no stacked-slice seams).
const HERO_GRADIENT = [
  "rgba(5,7,10,0.00)",
  "rgba(5,7,10,0.14)",
  "rgba(5,7,10,0.46)",
  "rgba(5,7,10,0.85)",
  "rgba(5,7,10,1.00)",
] as const;

const RATING_OPTIONS: {
  value: WatchedSentiment;
  label: string;
  icon: keyof typeof Ionicons.glyphMap;
  color: string;
}[] = [
  { value: "loved", label: "Loved it", icon: "heart", color: Colors.amber },
  { value: "liked", label: "Liked it", icon: "thumbs-up", color: Colors.success },
  { value: "neutral", label: "Okay", icon: "remove-circle", color: Colors.textSecondary },
  { value: "disliked", label: "Disliked", icon: "thumbs-down", color: Colors.danger },
];

export default function TitleDetail() {
  const params = useLocalSearchParams<{ id: string | string[] }>();
  const id = Array.isArray(params.id) ? params.id[0] : params.id;
  const insets = useSafeAreaInsets();
  const { user, refresh } = useAuth();

  const [actionBusy, setActionBusy] = useState(false);
  const [sentiment, setSentiment] = useState<WatchedSentiment | null>(null);
  const [sentimentBusy, setSentimentBusy] = useState(false);

  const movieQ = useQuery<MovieDetail>({
    queryKey: ["/movies", id],
    queryFn: ({ signal }) => fetchMovie(id as string, signal),
    enabled: !!id,
  });

  const servicesQ = useQuery({
    queryKey: ["/services"],
    queryFn: ({ signal }) => fetchServices(signal),
    staleTime: 10 * 60_000,
  });

  const similarQ = useQuery<SimilarItem[]>({
    queryKey: ["/movies", id, "similar"],
    queryFn: ({ signal }) => fetchSimilar(id as string, signal),
    enabled: !!id,
  });

  const movie = movieQ.data;

  useEffect(() => {
    if (!movie || !id) return;
    analytics.capture(EVENTS.TITLE_DETAILS_VIEWED, {
      content_id: id,
      media_type: movie.type,
      source: "direct",
    }, { dedupeKey: `detail:${id}` });
  }, [movie, id]);

  const savedIds = (user?.saved as string[] | undefined) || [];
  const watchedIds = (user?.watched as string[] | undefined) || [];
  const subs = (user?.subscriptions as string[] | undefined) || [];
  const isSaved = !!id && savedIds.includes(id);
  const isWatched = !!id && watchedIds.includes(id);

  const act = useCallback(
    async (action: ContentAction) => {
      if (!id || actionBusy) return;
      setActionBusy(true);
      try {
        Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light).catch(() => {});
        await postAction(id, action);
        if (action === "save" || action === "unsave") {
          analytics.capture(action === "save" ? EVENTS.WATCHLIST_ITEM_ADDED : EVENTS.WATCHLIST_ITEM_REMOVED, {
            content_id: id,
            media_type: movie?.type,
            source: "detail",
          }, { dedupeKey: `detail-action:${id}:${action}`, user });
        }
        await refresh();
      } catch {
        // surfaced via disabled state release; no user data logged
      } finally {
        setActionBusy(false);
      }
    },
    [id, actionBusy, refresh, movie?.type, user]
  );

  const onRateWatched = useCallback(
    async (value: WatchedSentiment) => {
      if (!id || sentimentBusy) return;
      setSentimentBusy(true);
      const prev = sentiment;
      setSentiment(value); // optimistic
      try {
        Haptics.selectionAsync().catch(() => {});
        await postWatchedFeedback(id, value, true);
        analytics.capture(EVENTS.WATCHED_FEEDBACK_SUBMITTED, {
          content_id: id,
          media_type: movie?.type,
          feedback: value,
          genres: movie?.genres,
          user_interaction_count: Number(user?.post_onboarding_interactions || 0),
          interaction_bucket: analytics.interactionBucket(Number(user?.post_onboarding_interactions || 0)),
        }, { user, dedupeKey: `title-feedback:${id}:${value}` });
      } catch {
        setSentiment(prev); // roll back on failure
      } finally {
        setSentimentBusy(false);
      }
    },
    [id, sentiment, sentimentBusy, movie, user]
  );

  const onShare = useCallback(async () => {
    if (!movie) return;
    const title = movie.title || "this title";
    try {
      analytics.capture(EVENTS.SHARE_STARTED, { content_id: id, media_type: movie.type, source: "title_details" }, { user });
      const result = await Share.share({
        message: `Check out ${title} on WatchSmart`,
      });
    } catch {
      // user dismissed or share unavailable
    }
  }, [movie, id, user]);

  const openTmdb = useCallback(() => {
    Linking.openURL(TMDB_URL).catch(() => {});
  }, []);

  // ── Loading ──────────────────────────────────────────────────────────────
  if (movieQ.isLoading) {
    return (
      <View style={styles.center}>
        <Stack.Screen options={{ headerShown: false }} />
        <ActivityIndicator color={Colors.amber} />
        <Text style={styles.centerText}>Loading title…</Text>
      </View>
    );
  }

  // ── Error ────────────────────────────────────────────────────────────────
  if (movieQ.isError || !movie) {
    const notFound = (movieQ.error as { response?: { status?: number } })?.response?.status === 404;
    return (
      <View style={styles.center}>
        <Stack.Screen options={{ headerShown: false }} />
        <Ionicons name="alert-circle-outline" size={44} color={Colors.textSecondary} />
        <Text style={styles.errorTitle}>Couldn&apos;t load</Text>
        <Text style={styles.centerText}>
          {notFound
            ? "We couldn't find that title."
            : "Couldn't load this title. Check your connection."}
        </Text>
        <View style={styles.errorButtons}>
          <Pressable
            onPress={() => movieQ.refetch()}
            style={({ pressed }) => [styles.primaryBtn, pressed && { opacity: 0.85 }]}
            accessibilityRole="button"
            accessibilityLabel="Try again"
          >
            <Text style={styles.primaryBtnText}>Try again</Text>
          </Pressable>
          <Pressable
            onPress={() => router.back()}
            style={({ pressed }) => [styles.secondaryBtn, pressed && { opacity: 0.85 }]}
            accessibilityRole="button"
            accessibilityLabel="Go back"
          >
            <Text style={styles.secondaryBtnText}>Go back</Text>
          </Pressable>
        </View>
      </View>
    );
  }

  const isTv = movie.type === "tv";
  const heroUri = movie.backdrop_url || movie.poster_url || null;
  const genres = (movie.genres || []).filter(Boolean).slice(0, 4);
  const cert = getCertification(movie);
  const runtime = formatRuntime(movie.runtime);
  const cast = (movie.cast_names || []).filter(Boolean).slice(0, 12);
  const services = servicesQ.data || [];
  const servicesById: Record<string, (typeof services)[number]> = {};
  for (const s of services) servicesById[s.id] = s;

  const available = (movie.available_on || []).filter(Boolean);
  const myProviders = available.filter((sid) => subs.includes(sid));
  const otherProviders = available.filter((sid) => !subs.includes(sid));
  const seasonsCount = (movie.seasons || []).length;

  return (
    <View style={styles.root}>
      <Stack.Screen options={{ headerShown: false }} />
      <ScrollView
        showsVerticalScrollIndicator={false}
        contentContainerStyle={{ paddingBottom: insets.bottom + 40 }}
      >
        {/* ── Hero ── */}
        <View style={[styles.hero, { height: HERO_H }]}>
          {heroUri ? (
            <Image source={{ uri: heroUri }} style={StyleSheet.absoluteFill} resizeMode="cover" />
          ) : (
            <View style={[StyleSheet.absoluteFill, styles.heroFallback]} />
          )}
          {/* Subtle top scrim so the back/share buttons stay legible. */}
          <LinearGradient
            colors={["rgba(5,7,10,0.55)", "rgba(5,7,10,0.0)"]}
            style={styles.scrimTop}
            pointerEvents="none"
          />
          {/* One smooth gradient into the page background — no visible band. */}
          <LinearGradient
            colors={[...HERO_GRADIENT]}
            style={styles.heroGradient}
            pointerEvents="none"
          />

          {/* Top bar */}
          <View style={[styles.topBar, { paddingTop: insets.top + 8 }]}>
            <Pressable
              onPress={() => router.back()}
              style={({ pressed }) => [styles.iconBtn, pressed && { opacity: 0.7 }]}
              accessibilityRole="button"
              accessibilityLabel="Go back"
              hitSlop={8}
            >
              <Ionicons name="arrow-back" size={22} color={Colors.text} />
            </Pressable>
            <Pressable
              onPress={onShare}
              style={({ pressed }) => [styles.iconBtn, pressed && { opacity: 0.7 }]}
              accessibilityRole="button"
              accessibilityLabel="Share this title"
              hitSlop={8}
            >
              <Ionicons name="share-outline" size={20} color={Colors.text} />
            </Pressable>
          </View>

          {/* Hero content */}
          <View style={styles.heroContent}>
            {genres.length > 0 ? (
              <View style={styles.genreRow}>
                {genres.map((g) => (
                  <View key={g} style={styles.genreChip}>
                    <Text style={styles.genreText}>{g}</Text>
                  </View>
                ))}
              </View>
            ) : null}
            <Text style={styles.title}>{movie.title || "Untitled"}</Text>
            <View style={styles.metaRow}>
              {typeof movie.rating === "number" && movie.rating > 0 ? (
                <View style={styles.metaItem}>
                  <Ionicons name="star" size={13} color={Colors.amber} />
                  <Text style={styles.metaText}>{movie.rating.toFixed(1)}</Text>
                </View>
              ) : null}
              {movie.year ? <Text style={styles.metaText}>{movie.year}</Text> : null}
              {isTv ? (
                <Text style={styles.metaText}>
                  {seasonsCount || 1} season{(seasonsCount || 1) !== 1 ? "s" : ""}
                </Text>
              ) : runtime ? (
                <Text style={styles.metaText}>{runtime}</Text>
              ) : null}
              {cert ? (
                <View style={styles.certChip}>
                  <Text style={styles.certText}>{cert}</Text>
                </View>
              ) : null}
            </View>
          </View>
        </View>

        {/* ── Actions ── */}
        <View
          style={[
            styles.actionRow,
            {
              paddingLeft: Math.max(20, insets.left + 20),
              paddingRight: Math.max(20, insets.right + 20),
            },
          ]}
        >
          <Pressable
            onPress={() => act(isSaved ? "unsave" : "save")}
            disabled={actionBusy}
            style={({ pressed }) => [
              styles.actionBtn,
              isSaved ? styles.actionBtnActive : styles.actionBtnIdle,
              (pressed || actionBusy) && { opacity: 0.7 },
            ]}
            accessibilityRole="button"
            accessibilityLabel={isSaved ? "Remove from watchlist" : "Save to watchlist"}
          >
            <Ionicons
              name={isSaved ? "heart" : "heart-outline"}
              size={18}
              color={isSaved ? Colors.obsidian : Colors.text}
            />
            <Text style={[styles.actionText, isSaved && styles.actionTextActive]}>
              {isSaved ? "Saved" : "Save"}
            </Text>
          </Pressable>
          <Pressable
            onPress={() => act(isWatched ? "unwatched" : "watched")}
            disabled={actionBusy}
            style={({ pressed }) => [
              styles.actionBtn,
              isWatched ? styles.actionBtnWatched : styles.actionBtnIdle,
              (pressed || actionBusy) && { opacity: 0.7 },
            ]}
            accessibilityRole="button"
            accessibilityLabel={isWatched ? "Mark as not watched" : "Mark as watched"}
          >
            <Ionicons name={isWatched ? "eye" : "eye-outline"} size={18} color={Colors.text} />
            <Text style={styles.actionText}>{isWatched ? "Watched" : "Watched"}</Text>
          </Pressable>
        </View>

        {/* ── Your rating (only when already watched) ── */}
        {isWatched && (
          <View style={styles.ratingRow} testID="your-rating-row">
            <Text style={styles.ratingLabel}>Your rating</Text>
            <View style={styles.ratingChips}>
              {RATING_OPTIONS.map((opt) => {
                const active = sentiment === opt.value;
                return (
                  <Pressable
                    key={opt.value}
                    onPress={() => onRateWatched(opt.value)}
                    disabled={sentimentBusy}
                    style={({ pressed }) => [
                      styles.ratingChip,
                      active && styles.ratingChipActive,
                      (pressed || sentimentBusy) && { opacity: 0.7 },
                    ]}
                    accessibilityRole="button"
                    accessibilityLabel={opt.label}
                    testID={`rating-${opt.value}`}
                  >
                    <Ionicons
                      name={opt.icon}
                      size={16}
                      color={active ? Colors.obsidian : opt.color}
                    />
                    <Text style={[styles.ratingChipText, active && styles.ratingChipTextActive]}>
                      {opt.label}
                    </Text>
                  </Pressable>
                );
              })}
            </View>
          </View>
        )}

        {/* ── Overview ── */}
        <View style={styles.body}>
          <Text style={styles.overview}>{movie.overview || "No description available."}</Text>

          {/* ── Where to watch ── */}
          <Text style={styles.sectionHeading}>Where to watch</Text>
          {available.length === 0 ? (
            <Text style={styles.mutedText}>
              {movie.availability_region_matched === false
                ? "We don't have confirmed availability for your region yet."
                : "Not currently streaming in your region."}
            </Text>
          ) : (
            <View style={styles.providerList}>
              {myProviders.map((sid) => (
                <ProviderRow key={sid} serviceId={sid} service={servicesById[sid]} included />
              ))}
              {otherProviders.map((sid) => (
                <ProviderRow key={sid} serviceId={sid} service={servicesById[sid]} />
              ))}
            </View>
          )}

          {/* ── Cast ── */}
          {cast.length > 0 ? (
            <>
              <Text style={styles.sectionHeading}>Cast</Text>
              <ScrollView
                horizontal
                showsHorizontalScrollIndicator={false}
                contentContainerStyle={styles.castScroll}
              >
                {cast.map((name) => (
                  <View key={name} style={styles.castChip}>
                    <Ionicons name="person" size={13} color={Colors.textSecondary} />
                    <Text style={styles.castName} numberOfLines={1}>
                      {name}
                    </Text>
                  </View>
                ))}
              </ScrollView>
            </>
          ) : null}
        </View>

        {/* ── Similar ── */}
        <SimilarRow
          items={similarQ.data || []}
          onPress={(m) => {
            analytics.capture(EVENTS.SIMILAR_TITLE_SELECTED, { content_id: m.id, media_type: m.type, source: "title_details" }, { user });
            engage(m.id, "search_click");
            router.push({
              pathname: "/title/[id]",
              params: { id: m.id, type: m.type || "movie" },
            });
          }}
        />

        {/* ── TMDB attribution ── */}
        <View style={styles.attribution}>
          <Text style={styles.attributionText}>Data provided by </Text>
          <Pressable onPress={openTmdb} accessibilityRole="link" accessibilityLabel="Open TMDB">
            <Text style={styles.attributionLink}>TMDB</Text>
          </Pressable>
        </View>
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: Colors.obsidian },
  center: {
    flex: 1,
    backgroundColor: Colors.obsidian,
    alignItems: "center",
    justifyContent: "center",
    paddingHorizontal: 32,
    gap: 12,
  },
  centerText: {
    fontFamily: "Inter_400Regular",
    fontSize: 14,
    color: Colors.textSecondary,
    textAlign: "center",
  },
  errorTitle: { fontFamily: "Inter_700Bold", fontSize: 22, color: Colors.text, marginTop: 4 },
  errorButtons: { flexDirection: "row", gap: 12, marginTop: 12 },
  primaryBtn: {
    backgroundColor: Colors.amber,
    borderRadius: 14,
    paddingHorizontal: 22,
    paddingVertical: 12,
  },
  primaryBtnText: { fontFamily: "Inter_700Bold", fontSize: 15, color: Colors.obsidian },
  secondaryBtn: {
    backgroundColor: Colors.surface,
    borderWidth: 1,
    borderColor: Colors.border,
    borderRadius: 14,
    paddingHorizontal: 22,
    paddingVertical: 12,
  },
  secondaryBtnText: { fontFamily: "Inter_600SemiBold", fontSize: 15, color: Colors.text },

  hero: { width: "100%", backgroundColor: Colors.velvet },
  heroFallback: { backgroundColor: Colors.velvet },
  scrimTop: {
    position: "absolute",
    top: 0,
    left: 0,
    right: 0,
    height: 130,
  },
  heroGradient: {
    position: "absolute",
    left: 0,
    right: 0,
    bottom: 0,
    height: "78%",
  },
  topBar: {
    position: "absolute",
    top: 0,
    left: 0,
    right: 0,
    flexDirection: "row",
    justifyContent: "space-between",
    paddingHorizontal: 16,
  },
  iconBtn: {
    width: 42,
    height: 42,
    borderRadius: 21,
    backgroundColor: "rgba(5,7,10,0.55)",
    borderWidth: 1,
    borderColor: Colors.border,
    alignItems: "center",
    justifyContent: "center",
  },
  heroContent: { position: "absolute", left: 0, right: 0, bottom: 0, paddingHorizontal: 20, paddingBottom: 20 },
  genreRow: { flexDirection: "row", flexWrap: "wrap", gap: 6, marginBottom: 10 },
  genreChip: {
    backgroundColor: "rgba(255,255,255,0.14)",
    borderRadius: 999,
    paddingHorizontal: 10,
    paddingVertical: 4,
  },
  genreText: {
    fontFamily: "Inter_600SemiBold",
    fontSize: 10,
    color: Colors.text,
    textTransform: "uppercase",
    letterSpacing: 0.6,
  },
  title: { fontFamily: "Inter_800ExtraBold", fontSize: 32, color: Colors.text, lineHeight: 36 },
  metaRow: { flexDirection: "row", alignItems: "center", flexWrap: "wrap", gap: 12, marginTop: 10 },
  metaItem: { flexDirection: "row", alignItems: "center", gap: 4 },
  metaText: { fontFamily: "Inter_500Medium", fontSize: 13, color: Colors.textSecondary },
  certChip: {
    borderWidth: 1,
    borderColor: Colors.borderStrong,
    borderRadius: 6,
    paddingHorizontal: 6,
    paddingVertical: 1,
  },
  certText: { fontFamily: "Inter_600SemiBold", fontSize: 11, color: Colors.textSecondary },

  actionRow: { flexDirection: "row", gap: 12, marginTop: 20 },
  actionBtn: {
    flex: 1,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 8,
    borderRadius: 16,
    paddingVertical: 14,
  },
  actionBtnIdle: { backgroundColor: Colors.surface, borderWidth: 1, borderColor: Colors.border },
  actionBtnActive: { backgroundColor: Colors.amber },
  actionBtnWatched: { backgroundColor: Colors.surfaceLight, borderWidth: 1, borderColor: Colors.borderStrong },
  actionText: { fontFamily: "Inter_700Bold", fontSize: 15, color: Colors.text },
  actionTextActive: { color: Colors.obsidian },

  ratingRow: { paddingHorizontal: 20, marginTop: 20 },
  ratingLabel: {
    fontFamily: "Inter_600SemiBold",
    fontSize: 11,
    letterSpacing: 1,
    textTransform: "uppercase",
    color: Colors.textTertiary,
    marginBottom: 10,
  },
  ratingChips: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  ratingChip: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    backgroundColor: Colors.surface,
    borderWidth: 1,
    borderColor: Colors.border,
    borderRadius: 999,
    paddingHorizontal: 14,
    paddingVertical: 9,
  },
  ratingChipActive: { backgroundColor: Colors.amber, borderColor: Colors.amber },
  ratingChipText: { fontFamily: "Inter_600SemiBold", fontSize: 13, color: Colors.text },
  ratingChipTextActive: { color: Colors.obsidian },

  body: { paddingHorizontal: 20, marginTop: 20 },
  overview: {
    fontFamily: "Inter_400Regular",
    fontSize: 15,
    lineHeight: 23,
    color: Colors.textSecondary,
  },
  sectionHeading: {
    fontFamily: "Inter_700Bold",
    fontSize: 17,
    color: Colors.text,
    marginTop: 24,
    marginBottom: 12,
  },
  mutedText: { fontFamily: "Inter_400Regular", fontSize: 14, color: Colors.textTertiary },
  providerList: { gap: 10 },
  castScroll: { gap: 8, paddingRight: 8 },
  castChip: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    backgroundColor: Colors.surface,
    borderWidth: 1,
    borderColor: Colors.border,
    borderRadius: 999,
    paddingHorizontal: 12,
    paddingVertical: 8,
    maxWidth: 180,
  },
  castName: { fontFamily: "Inter_500Medium", fontSize: 13, color: Colors.text },

  attribution: {
    flexDirection: "row",
    justifyContent: "center",
    alignItems: "center",
    marginTop: 36,
    paddingHorizontal: 20,
  },
  attributionText: { fontFamily: "Inter_400Regular", fontSize: 12, color: Colors.textTertiary },
  attributionLink: {
    fontFamily: "Inter_600SemiBold",
    fontSize: 12,
    color: Colors.amber,
    textDecorationLine: "underline",
  },
});
