import { Ionicons } from "@expo/vector-icons";
import { Image } from "expo-image";
import * as Haptics from "expo-haptics";
import { router } from "expo-router";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { LinearGradient } from "expo-linear-gradient";
import {
  ActivityIndicator,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { OnboardingProgress } from "@/components/onboarding/OnboardingProgress";
import { Colors } from "@/constants/colors";
import { useAuth } from "@/context/AuthContext";
import { getFriendlyMessage } from "@/lib/api";
import {
  OnboardingTitle,
  RateValue,
  completeOnboarding,
  fetchOnboardingTitles,
  fetchOnboardingProgress,
  rateTitle,
} from "@/lib/onboarding-api";
import { analytics, EVENTS } from "@/lib/analytics";

export default function OnboardingTaste() {
  const { user, setUser } = useAuth();
  const insets = useSafeAreaInsets();
  const [idx, setIdx] = useState(0);
  const [ratedCount, setRatedCount] = useState<number | null>(null);
  const [ratingBusy, setRatingBusy] = useState(false);
  const [finishing, setFinishing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [earlyPromptDismissed, setEarlyPromptDismissed] = useState(false);

  const progressQuery = useQuery({
    queryKey: ["/onboarding/progress", user?.user_id],
    queryFn: fetchOnboardingProgress,
    staleTime: 0,
    refetchOnWindowFocus: false,
  });
  const progress = progressQuery.data;
  const interactions = ratedCount ?? progress?.interactions ?? 0;
  const minimumInteractions = progress?.minimum_interactions ?? 5;
  const maximumInteractions = progress?.maximum_interactions ?? 10;

  const query = useQuery<OnboardingTitle[]>({
    queryKey: ["/onboarding/titles", user?.user_id, user?.genres],
    queryFn: () => fetchOnboardingTitles(10),
    enabled: !progressQuery.isLoading && !progressQuery.isError,
    staleTime: 0,
    refetchOnWindowFocus: false,
  });
  const titles = query.data ?? [];
  const current = titles[idx];
  const supplyExhausted = !query.isLoading && !query.isError && (titles.length === 0 || idx >= titles.length);
  const canFinish = !progressQuery.isLoading && Boolean(
    progress?.can_finish || progress?.is_complete || supplyExhausted
  );
  const done = titles.length > 0 && idx >= titles.length;

  const rate = async (rating: RateValue) => {
    if (ratingBusy || !current) return;
    setRatingBusy(true);
    setError(null);
    const movieId = current.id;
    try {
      Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
      const r = await rateTitle(movieId, rating);
      analytics.capture(EVENTS.ONBOARDING_TITLE_FEEDBACK, { content_id: movieId, media_type: current.type, feedback: rating, position: idx }, { dedupeKey: `onboarding-rating:${movieId}`, user: r.user || user });
      if (r.user) setUser(r.user);
      // Skip is neutral to taste, but still counts as a deliberate onboarding
      // interaction toward the minimum.
      setRatedCount(interactions + 1);
      setIdx((i) => i + 1);
      await progressQuery.refetch();
    } catch (e) {
      Haptics.notificationAsync(Haptics.NotificationFeedbackType.Error);
      setError(getFriendlyMessage(e));
    } finally {
      setRatingBusy(false);
    }
  };

  const finish = async () => {
    if (finishing || !canFinish) return;
    setFinishing(true);
    setError(null);
    try {
      const updated = await completeOnboarding();
      setUser(updated);
      analytics.capture(EVENTS.ONBOARDING_COMPLETED, { rated_count: interactions }, { user: updated, allowDuplicate: true });
      Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success);
      // First-open tutorial is shown once, after account creation + initial
      // service selection (i.e. at the end of onboarding). It gates itself on
      // the user's tutorial_completed_at, so completed users skip it.
      if (updated.tutorial_completed_at) {
        router.replace("/(tabs)/discover");
      } else {
        router.replace("/tutorial");
      }
    } catch (e) {
      Haptics.notificationAsync(Haptics.NotificationFeedbackType.Error);
      setError(getFriendlyMessage(e));
    } finally {
      setFinishing(false);
    }
  };

  const showDeck = !progressQuery.isLoading && !progressQuery.isError
    && !query.isLoading && !query.isError && titles.length > 0 && !done;
  const showDone = done || supplyExhausted;

  return (
    <View style={styles.root}>
      <ScrollView
        contentContainerStyle={[
          styles.content,
          { paddingTop: insets.top + 20, paddingBottom: 180 },
        ]}
      >
        <OnboardingProgress step={4} />
        <Text style={styles.eyebrow}>Step 4 of 4</Text>
        <Text style={styles.h1}>Quick taste check</Text>
        <Text style={styles.sub}>
          Up to 10 titles based on your genres. Your deliberate choices shape your first picks.
        </Text>

        {progressQuery.isLoading ? (
          <View style={styles.centerTall}>
            <ActivityIndicator color={Colors.amber} />
          </View>
        ) : progressQuery.isError ? (
          <View style={styles.centerTall}>
            <Text style={styles.errorText}>Couldn&apos;t resume your taste check.</Text>
            <Pressable
              onPress={() => progressQuery.refetch()}
              style={styles.retryBtn}
              accessibilityRole="button"
              accessibilityLabel="Retry loading onboarding progress"
              testID="retry-onboarding-progress"
            >
              <Text style={styles.retryText}>Try again</Text>
            </Pressable>
          </View>
        ) : query.isLoading ? (
          <View style={styles.centerTall}>
            <ActivityIndicator color={Colors.amber} />
          </View>
        ) : query.isError ? (
          <View style={styles.centerTall}>
            <Text style={styles.errorText}>Couldn&apos;t load titles.</Text>
            <Pressable
              onPress={() => query.refetch()}
              style={styles.retryBtn}
              accessibilityRole="button"
              accessibilityLabel="Retry loading titles"
            >
              <Text style={styles.retryText}>Retry</Text>
            </Pressable>
          </View>
        ) : showDone ? (
          <View style={styles.doneCard}>
            <Ionicons name="sparkles" size={28} color={Colors.amber} />
            <Text style={styles.doneTitle}>
              {titles.length === 0
                ? "You're all set"
                  : `${interactions} interaction${interactions === 1 ? "" : "s"} in`}
            </Text>
            <Text style={styles.doneSub}>
                Your feed is already learning. Finish now, or keep going for stronger personalisation.
            </Text>
          </View>
        ) : showDeck && current ? (
          <View>
            <View style={styles.card}>
              {current.poster_url ? (
                <Image
                  source={{ uri: current.poster_url }}
                  style={styles.poster}
                  contentFit="cover"
                  transition={200}
                />
              ) : (
                <View style={[styles.poster, styles.posterFallback]}>
                  <Ionicons name="film-outline" size={48} color={Colors.textTertiary} />
                </View>
              )}
              {/* Smooth gradient scrim so card text stays legible over bright artwork on device. */}
              <LinearGradient
                colors={["rgba(5,7,10,0.00)", "rgba(5,7,10,0.18)", "rgba(5,7,10,0.72)", "rgba(5,7,10,0.90)"]}
                style={styles.cardOverlay}
                pointerEvents="none"
              />
              <View style={styles.badgeRow} pointerEvents="none">
                <View style={styles.badge}>
                  <Ionicons name="star" size={11} color={Colors.amber} />
                  <Text style={styles.badgeText}>
                    {typeof current.rating === "number" ? current.rating.toFixed(1) : "—"}
                  </Text>
                  <Text style={styles.badgeType}>
                    {current.type === "tv" ? "TV" : "Film"}
                  </Text>
                </View>
              </View>
              <View style={styles.cardInfo} pointerEvents="none">
                {current.genres && current.genres.length > 0 ? (
                  <Text style={styles.cardGenres}>{current.genres.join(" · ")}</Text>
                ) : null}
                <Text style={styles.cardTitle} numberOfLines={2}>
                  {current.title}
                  {current.year ? (
                    <Text style={styles.cardYear}> ({current.year})</Text>
                  ) : null}
                </Text>
                {current.overview ? (
                  <Text style={styles.cardOverview} numberOfLines={3}>
                    {current.overview}
                  </Text>
                ) : null}
              </View>
            </View>

            <Text style={styles.progressText}>
              {interactions} of {maximumInteractions} interactions · feed updates live
            </Text>

            {error ? <Text style={[styles.errorText, { marginTop: 12 }]}>{error}</Text> : null}
            {canFinish && !earlyPromptDismissed ? (
              <View style={styles.finishNudge} testID="early-finish">
                <View style={{ flex: 1 }}>
                  <Text style={styles.finishNudgeTitle}>
                    {interactions >= maximumInteractions
                      ? "Taste check complete"
                      : `${minimumInteractions} choices is enough to start`}
                  </Text>
                  <Text style={styles.finishNudgeBody}>
                    Keep rating to 10 for stronger personalisation, or finish now.
                  </Text>
                </View>
                <View style={styles.finishNudgeActions}>
                  <Pressable
                    onPress={() => setEarlyPromptDismissed(true)}
                    accessibilityRole="button"
                    accessibilityLabel="Continue to 10"
                    testID="continue-to-10"
                  >
                    <Text style={styles.finishNudgeContinue}>Continue to 10</Text>
                  </Pressable>
                  <Pressable
                    onPress={finish}
                    disabled={finishing}
                    accessibilityRole="button"
                    accessibilityLabel="Finish onboarding now"
                    testID="finish-early"
                  >
                    <Text style={styles.finishNudgeAction}>Finish now</Text>
                  </Pressable>
                </View>
              </View>
            ) : null}
          </View>
        ) : null}
      </ScrollView>

      <View style={[styles.bottomBar, { paddingBottom: insets.bottom + 16 }]}>
        {showDeck && current ? (
          <View style={styles.actions}>
            <Pressable
              onPress={() => rate("dislike")}
              disabled={ratingBusy}
              style={[styles.actionBtn, styles.dislikeBtn, ratingBusy && styles.btnDisabled]}
              accessibilityRole="button"
              accessibilityLabel="Not for me"
              testID="rate-dislike"
            >
              <Ionicons name="thumbs-down" size={22} color="#FCA5A5" />
            </Pressable>
            <Pressable
              onPress={() => rate("skip")}
              disabled={ratingBusy}
              style={[styles.actionBtn, styles.skipBtn, ratingBusy && styles.btnDisabled]}
              accessibilityRole="button"
              accessibilityLabel="Skip"
              testID="rate-skip"
            >
              <Ionicons name="play-skip-forward" size={18} color={Colors.textSecondary} />
            </Pressable>
            <Pressable
              onPress={() => rate("like")}
              disabled={ratingBusy}
              style={[styles.actionBtn, styles.likeBtn, ratingBusy && styles.btnDisabled]}
              accessibilityRole="button"
              accessibilityLabel="Love it"
              testID="rate-like"
            >
              <Ionicons name="thumbs-up" size={22} color="#0B0500" />
            </Pressable>
          </View>
        ) : (
          <Pressable
            onPress={finish}
            disabled={finishing || query.isLoading || progressQuery.isLoading || !canFinish}
            style={[
              styles.primaryBtn,
              (finishing || query.isLoading || progressQuery.isLoading || !canFinish) && styles.btnDisabled,
            ]}
            accessibilityRole="button"
            accessibilityLabel={canFinish ? "Get my picks" : `${minimumInteractions} interactions required`}
          >
            {finishing ? (
              <ActivityIndicator color="#0B0500" />
            ) : (
              <Text style={styles.primaryBtnText}>Get my picks</Text>
            )}
          </Pressable>
        )}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: Colors.obsidian },
  content: { paddingHorizontal: 24 },
  eyebrow: {
    fontFamily: "Inter_600SemiBold",
    fontSize: 11,
    letterSpacing: 2,
    textTransform: "uppercase",
    color: Colors.amber,
    marginTop: 8,
  },
  h1: {
    fontFamily: "Inter_800ExtraBold",
    fontSize: 32,
    color: Colors.text,
    marginTop: 10,
    lineHeight: 36,
  },
  sub: {
    fontFamily: "Inter_400Regular",
    fontSize: 15,
    color: Colors.textSecondary,
    marginTop: 10,
    marginBottom: 20,
    lineHeight: 21,
  },
  centerTall: {
    alignItems: "center",
    justifyContent: "center",
    paddingVertical: 80,
    gap: 16,
  },
  card: {
    height: 440,
    borderRadius: 24,
    overflow: "hidden",
    borderWidth: 1,
    borderColor: Colors.border,
    backgroundColor: Colors.velvet,
  },
  poster: {
    position: "absolute",
    top: 0,
    left: 0,
    right: 0,
    bottom: 0,
    width: "100%",
    height: "100%",
  },
  posterFallback: { alignItems: "center", justifyContent: "center" },
  cardOverlay: {
    position: "absolute",
    top: 0,
    left: 0,
    right: 0,
    bottom: 0,
  },
  badgeRow: { position: "absolute", top: 14, left: 14 },
  badge: {
    flexDirection: "row",
    alignItems: "center",
    gap: 5,
    backgroundColor: "rgba(0,0,0,0.55)",
    borderWidth: 1,
    borderColor: Colors.borderStrong,
    borderRadius: 999,
    paddingHorizontal: 10,
    paddingVertical: 5,
  },
  badgeText: { fontFamily: "Inter_600SemiBold", fontSize: 12, color: Colors.text },
  badgeType: {
    fontFamily: "Inter_500Medium",
    fontSize: 10,
    letterSpacing: 1,
    color: Colors.textSecondary,
    textTransform: "uppercase",
    marginLeft: 2,
  },
  cardInfo: { position: "absolute", left: 18, right: 18, bottom: 18 },
  cardGenres: {
    fontFamily: "Inter_600SemiBold",
    fontSize: 10,
    letterSpacing: 1.5,
    textTransform: "uppercase",
    color: Colors.amber,
    marginBottom: 6,
  },
  cardTitle: { fontFamily: "Inter_800ExtraBold", fontSize: 24, color: Colors.text },
  cardYear: { fontFamily: "Inter_500Medium", fontSize: 18, color: Colors.textSecondary },
  cardOverview: {
    fontFamily: "Inter_400Regular",
    fontSize: 13,
    color: "rgba(255,255,255,0.85)",
    marginTop: 8,
    lineHeight: 19,
  },
  progressText: {
    fontFamily: "Inter_500Medium",
    fontSize: 12,
    color: Colors.textTertiary,
    textAlign: "center",
    marginTop: 16,
  },
  finishNudge: {
    flexDirection: "row",
    alignItems: "center",
    gap: 12,
    marginTop: 14,
    padding: 14,
    borderRadius: 16,
    borderWidth: 1,
    borderColor: "rgba(255,122,24,0.25)",
    backgroundColor: "rgba(255,122,24,0.06)",
  },
  finishNudgeTitle: {
    fontFamily: "Inter_600SemiBold",
    fontSize: 13,
    color: Colors.text,
  },
  finishNudgeBody: {
    fontFamily: "Inter_400Regular",
    fontSize: 12,
    lineHeight: 17,
    color: Colors.textSecondary,
    marginTop: 3,
  },
  finishNudgeAction: {
    fontFamily: "Inter_700Bold",
    fontSize: 12,
    color: Colors.amber,
  },
  finishNudgeActions: { alignItems: "flex-end", gap: 8 },
  finishNudgeContinue: {
    fontFamily: "Inter_500Medium",
    fontSize: 11,
    color: Colors.textSecondary,
  },
  doneCard: {
    borderRadius: 24,
    borderWidth: 1,
    borderColor: Colors.border,
    backgroundColor: Colors.velvet,
    padding: 32,
    alignItems: "center",
    gap: 12,
    marginTop: 20,
  },
  doneTitle: { fontFamily: "Inter_700Bold", fontSize: 20, color: Colors.text },
  doneSub: {
    fontFamily: "Inter_400Regular",
    fontSize: 14,
    color: Colors.textSecondary,
    textAlign: "center",
    lineHeight: 20,
  },
  bottomBar: {
    position: "absolute",
    left: 0,
    right: 0,
    bottom: 0,
    paddingHorizontal: 24,
    paddingTop: 16,
    backgroundColor: Colors.velvet,
    borderTopWidth: 1,
    borderTopColor: Colors.border,
  },
  actions: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 20,
  },
  actionBtn: {
    width: 60,
    height: 60,
    borderRadius: 30,
    alignItems: "center",
    justifyContent: "center",
    borderWidth: 1,
  },
  dislikeBtn: {
    backgroundColor: "rgba(239,68,68,0.15)",
    borderColor: "rgba(239,68,68,0.40)",
  },
  skipBtn: {
    width: 50,
    height: 50,
    borderRadius: 25,
    backgroundColor: "rgba(255,255,255,0.04)",
    borderColor: Colors.border,
  },
  likeBtn: { backgroundColor: Colors.amber, borderColor: Colors.amber },
  primaryBtn: {
    backgroundColor: Colors.amber,
    paddingVertical: 16,
    borderRadius: 16,
    alignItems: "center",
    justifyContent: "center",
  },
  primaryBtnText: { fontFamily: "Inter_700Bold", fontSize: 16, color: "#0B0500" },
  btnDisabled: { opacity: 0.5 },
  retryBtn: {
    borderWidth: 1,
    borderColor: Colors.border,
    borderRadius: 12,
    paddingHorizontal: 20,
    paddingVertical: 10,
  },
  retryText: { fontFamily: "Inter_600SemiBold", fontSize: 14, color: Colors.text },
  errorText: {
    fontFamily: "Inter_500Medium",
    fontSize: 14,
    color: Colors.danger,
    textAlign: "center",
  },
});
