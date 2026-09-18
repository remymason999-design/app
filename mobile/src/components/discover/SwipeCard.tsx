/**
 * SwipeCard — a single Discover card with pan-gesture swiping.
 *
 * Mirrors the web app's Card (frontend/src/pages/Discover.jsx):
 *   - backdrop-first artwork with a bottom gradient scrim,
 *   - SAVE / SKIP / WATCHED overlay stamps that fade in as you drag,
 *   - title / rating / year / runtime / genres / overview,
 *   - "Included with X" provider pill (or a plain provider count).
 *
 * Swipe directions: right = save, left = skip, up = watched. Only the top
 * card is interactive; the two behind it are static, scaled placeholders.
 */
import { Ionicons } from "@expo/vector-icons";
import { LinearGradient } from "expo-linear-gradient";
import React, { useCallback, useEffect } from "react";
import { Image, Pressable, StyleSheet, Text, View, useWindowDimensions } from "react-native";
import { Gesture, GestureDetector } from "react-native-gesture-handler";
import Animated, {
  Extrapolation,
  interpolate,
  runOnJS,
  useAnimatedStyle,
  useSharedValue,
  withSpring,
  withTiming,
} from "react-native-reanimated";

import { ProviderLogo } from "@/components/ProviderLogo";
import { Colors } from "@/constants/colors";
import {
  DiscoverCard,
  StreamingService,
  formatRuntime,
} from "@/lib/discover-api";
import { providerDisplayName } from "@/lib/providers";

const SWIPE_THRESHOLD = 110;
const SPRING = { stiffness: 260, damping: 28 } as const;

// A single TRUE smooth transparent → near-black gradient rendered by
// expo-linear-gradient — no stacked layers, no visible bands/seams. The bottom
// portion is dark enough for high-contrast text while artwork stays vibrant.
const GRADIENT_STOPS = [
  "rgba(5,7,10,0.00)",
  "rgba(5,7,10,0.16)",
  "rgba(5,7,10,0.46)",
  "rgba(5,7,10,0.78)",
  "rgba(5,7,10,0.90)",
] as const;

export type SwipeDir = "right" | "left" | "up";

interface Props {
  card: DiscoverCard;
  servicesById: Record<string, StreamingService>;
  userSubs: string[];
  isTop: boolean;
  stackPos: number; // 0 = top, 1, 2 behind
  disabled: boolean; // an action is already in flight
  onSwipe: (dir: SwipeDir) => void;
  onTap: () => void;
}

function SwipeCardImpl({
  card,
  servicesById,
  userSubs,
  isTop,
  stackPos,
  disabled,
  onSwipe,
  onTap,
}: Props) {
  const { width, height } = useWindowDimensions();
  const translateX = useSharedValue(0);
  const translateY = useSharedValue(0);

  // Reset the shared values whenever this card becomes the top card (e.g. after
  // a rewind pushes it back onto the stack) so it starts perfectly centred.
  useEffect(() => {
    translateX.value = 0;
    translateY.value = 0;
  }, [card.id, isTop, translateX, translateY]);

  const fling = useCallback(
    (dir: SwipeDir) => {
      if (dir === "right") {
        translateX.value = withTiming(width * 1.5, { duration: 220 });
        onSwipe(dir);
      } else if (dir === "left") {
        translateX.value = withTiming(-width * 1.5, { duration: 220 });
        onSwipe(dir);
      } else {
        // "watched" (up): don't fling the card off-screen. The parent opens a
        // feedback sheet first; the card must stay put so it can either spring
        // back (cancel) or advance cleanly (confirm). Spring back to centre.
        translateX.value = withSpring(0, SPRING);
        translateY.value = withSpring(0, SPRING);
        onSwipe(dir);
      }
    },
    [width, height, onSwipe, translateX, translateY]
  );

  const pan = Gesture.Pan()
    .enabled(isTop && !disabled)
    .onUpdate((e) => {
      translateX.value = e.translationX;
      translateY.value = e.translationY;
    })
    .onEnd((e) => {
      const dx = e.translationX;
      const dy = e.translationY;
      if (Math.abs(dy) > Math.abs(dx) && dy < -SWIPE_THRESHOLD) {
        runOnJS(fling)("up");
      } else if (dx > SWIPE_THRESHOLD) {
        runOnJS(fling)("right");
      } else if (dx < -SWIPE_THRESHOLD) {
        runOnJS(fling)("left");
      } else {
        translateX.value = withSpring(0, SPRING);
        translateY.value = withSpring(0, SPRING);
      }
    });

  const cardStyle = useAnimatedStyle(() => {
    if (!isTop) {
      // Underneath cards sit at EXACTLY the same size and position as the top
      // card so nothing bleeds out from behind it — the top card fully covers
      // them. Only stackPos 1 is ever meaningfully visible (during the top
      // card's swipe-out), and even then only its artwork shows.
      return { transform: [{ scale: 1 }], opacity: 1 };
    }
    const rotate = interpolate(
      translateX.value,
      [-width, 0, width],
      [-12, 0, 12],
      Extrapolation.CLAMP
    );
    return {
      transform: [
        { translateX: translateX.value },
        { translateY: translateY.value },
        { rotate: `${rotate}deg` },
      ],
    };
  });

  const saveStamp = useAnimatedStyle(() => ({
    opacity: interpolate(translateX.value, [40, 140], [0, 1], Extrapolation.CLAMP),
  }));
  const skipStamp = useAnimatedStyle(() => ({
    opacity: interpolate(translateX.value, [-140, -40], [1, 0], Extrapolation.CLAMP),
  }));
  const watchedStamp = useAnimatedStyle(() => ({
    opacity: interpolate(translateY.value, [-140, -40], [1, 0], Extrapolation.CLAMP),
  }));

  const artwork = card.backdrop_url || card.poster_url;
  const runtimeLabel =
    card.type === "tv"
      ? `${card.seasons?.length || 1} season${(card.seasons?.length || 1) > 1 ? "s" : ""}`
      : formatRuntime(card.runtime) || "—";
  const whyShown = card._signals?.why_shown || card.reason;

  const provider = renderProvider(card, userSubs, servicesById);

  return (
    <Animated.View
      style={[
        styles.card,
        // The top card must be fully opaque so nothing shows through it.
        isTop && styles.cardTop,
        { zIndex: 10 - stackPos },
        cardStyle,
      ]}
      testID={isTop ? "discover-card-top" : `discover-card-${stackPos}`}
    >
      <GestureDetector gesture={pan}>
        <Pressable
          style={StyleSheet.absoluteFill}
          onPress={isTop && !disabled ? onTap : undefined}
          accessibilityRole="button"
          accessibilityLabel={`${card.title}. Open details`}
        >
          {artwork ? (
            <Image source={{ uri: artwork }} style={styles.image} resizeMode="cover" />
          ) : (
            <View style={styles.noArt}>
              {isTop && <Text style={styles.noArtText}>No artwork available</Text>}
            </View>
          )}

          {/* Everything below is text / badges — gate ALL of it on isTop so the
              underneath cards render artwork only (no duplicate titles etc). */}
          {isTop && (
            <>
              {/* One smooth vertical gradient (transparent → near-black) — a
                  real linear gradient, so no band/seam is possible. The text
                  block sits on the darkest part at the bottom. */}
              <LinearGradient
                colors={[...GRADIENT_STOPS]}
                style={styles.gradient}
                pointerEvents="none"
              />

              <Animated.View style={[styles.stamp, styles.stampSave, saveStamp]}>
                <Text style={[styles.stampText, { color: Colors.amber }]}>SAVE</Text>
              </Animated.View>
              <Animated.View style={[styles.stamp, styles.stampSkip, skipStamp]}>
                <Text style={[styles.stampText, { color: "#E5E7EB" }]}>SKIP</Text>
              </Animated.View>
              <Animated.View style={[styles.stampWatched, watchedStamp]}>
                <Text style={[styles.stampText, { color: Colors.success }]}>WATCHED</Text>
              </Animated.View>

              {typeof card.match === "number" && (
                <View style={styles.matchBadge}>
                  <View style={styles.matchDot} />
                  <Text style={styles.matchText}>{card.match}% Match</Text>
                </View>
              )}

              <View style={styles.info}>
                {!!whyShown && (
                  <View style={styles.whyRow}>
                    <Ionicons name="sparkles" size={12} color={Colors.amber} />
                    <Text style={styles.whyText} numberOfLines={1}>
                      {whyShown}
                    </Text>
                  </View>
                )}
                <Text style={styles.title} numberOfLines={2}>
                  {card.title}
                </Text>
                <View style={styles.metaRow}>
                  {typeof card.rating === "number" && (
                    <View style={styles.metaItem}>
                      <Ionicons name="star" size={13} color={Colors.amber} />
                      <Text style={styles.metaText}>{card.rating.toFixed(1)}</Text>
                    </View>
                  )}
                  {!!card.year && (
                    <>
                      <Text style={styles.metaDot}>•</Text>
                      <Text style={styles.metaText}>{card.year}</Text>
                    </>
                  )}
                  <Text style={styles.metaDot}>•</Text>
                  <Text style={styles.metaText}>{runtimeLabel}</Text>
                </View>
                {(card.genres || []).length > 0 && (
                  <View style={styles.pillRow}>
                    {(card.genres || []).slice(0, 3).map((g) => (
                      <View key={g} style={styles.genrePill}>
                        <Text style={styles.genreText}>{g}</Text>
                      </View>
                    ))}
                  </View>
                )}
                {!!card.overview && (
                  <Text style={styles.overview} numberOfLines={3}>
                    {card.overview}
                  </Text>
                )}
                {provider}
              </View>
            </>
          )}
        </Pressable>
      </GestureDetector>

      {isTop && (
        <Pressable
          onPress={onTap}
          disabled={disabled}
          hitSlop={8}
          style={styles.infoBtn}
          accessibilityRole="button"
          accessibilityLabel="View details"
        >
          <Ionicons name="information-circle-outline" size={22} color="#E5E7EB" />
        </Pressable>
      )}
    </Animated.View>
  );
}

function renderProvider(
  card: DiscoverCard,
  userSubs: string[],
  servicesById: Record<string, StreamingService>
): React.ReactNode {
  const available = card.available_on || [];
  if (available.length === 0) return null;
  const onSub = available.filter((sid) => userSubs.includes(sid));
  if (onSub.length > 0) {
    const first = onSub[0];
    const name = providerDisplayName(first, servicesById[first]?.name);
    return (
      <View style={styles.includedPill} testID="provider-included-badge">
        <ProviderLogo
          sid={first}
          name={servicesById[first]?.name}
          logoUrl={servicesById[first]?.logo_path}
          size={20}
          radius={6}
        />
        <Text style={styles.includedText} numberOfLines={1}>
          Included with {name}
          {onSub.length > 1 ? ` +${onSub.length - 1}` : ""}
        </Text>
        <Ionicons name="checkmark-circle" size={14} color={Colors.success} />
      </View>
    );
  }
  const visible = available.slice(0, 3);
  const overflow = available.length - visible.length;
  return (
    <View style={styles.providerRow}>
      {visible.map((sid) => (
        <View key={sid} style={styles.providerChip}>
          <ProviderLogo
            sid={sid}
            name={servicesById[sid]?.name}
            logoUrl={servicesById[sid]?.logo_path}
            size={16}
            radius={5}
          />
          <Text style={styles.providerChipText} numberOfLines={1}>
            {providerDisplayName(sid, servicesById[sid]?.name)}
          </Text>
        </View>
      ))}
      {overflow > 0 && (
        <View style={styles.providerChip}>
          <Text style={styles.providerChipText}>+{overflow}</Text>
        </View>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    position: "absolute",
    top: 0,
    left: 0,
    right: 0,
    bottom: 0,
    borderRadius: 24,
    overflow: "hidden",
    // Solid opaque background so nothing shows through the artwork.
    backgroundColor: Colors.velvet,
  },
  cardTop: {
    // The active card must be fully opaque.
    opacity: 1,
    backgroundColor: Colors.velvet,
  },
  image: { ...StyleSheet.absoluteFillObject, width: "100%", height: "100%" },
  noArt: {
    ...StyleSheet.absoluteFillObject,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: "#0A0D12",
  },
  noArtText: { color: Colors.textTertiary, fontFamily: "Inter_500Medium", fontSize: 14 },
  // Single smooth gradient occupying the bottom ~70% of the card — one real
  // linear gradient (transparent → near-black) with no visible edges.
  gradient: {
    position: "absolute",
    left: 0,
    right: 0,
    bottom: 0,
    height: "70%",
  },
  stamp: {
    position: "absolute",
    top: 28,
    paddingHorizontal: 16,
    paddingVertical: 8,
    borderWidth: 2,
    borderRadius: 8,
    zIndex: 20,
  },
  stampSave: { right: 20, borderColor: Colors.amber, transform: [{ rotate: "12deg" }] },
  stampSkip: { left: 20, borderColor: "#D1D5DB", transform: [{ rotate: "-12deg" }] },
  stampWatched: {
    position: "absolute",
    top: "45%",
    alignSelf: "center",
    paddingHorizontal: 16,
    paddingVertical: 8,
    borderWidth: 2,
    borderRadius: 8,
    borderColor: Colors.success,
    zIndex: 20,
  },
  stampText: { fontFamily: "Inter_800ExtraBold", fontSize: 24, letterSpacing: 1 },
  matchBadge: {
    position: "absolute",
    top: 16,
    left: 16,
    zIndex: 20,
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    backgroundColor: "rgba(0,0,0,0.55)",
    borderWidth: 1,
    borderColor: "rgba(34,197,94,0.3)",
    borderRadius: 999,
    paddingHorizontal: 10,
    paddingVertical: 4,
  },
  matchDot: { width: 6, height: 6, borderRadius: 3, backgroundColor: Colors.success },
  matchText: { fontFamily: "Inter_600SemiBold", fontSize: 12, color: Colors.success },
  infoBtn: {
    position: "absolute",
    top: 14,
    right: 14,
    zIndex: 20,
    height: 40,
    width: 40,
    borderRadius: 20,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: "rgba(255,255,255,0.08)",
    borderWidth: 1,
    borderColor: Colors.border,
  },
  info: { position: "absolute", left: 0, right: 0, bottom: 0, padding: 22 },
  whyRow: { flexDirection: "row", alignItems: "center", gap: 6, marginBottom: 8 },
  whyText: { flex: 1, fontFamily: "Inter_500Medium", fontSize: 11, color: "rgba(255,122,24,0.9)" },
  title: {
    fontFamily: "Inter_800ExtraBold",
    fontSize: 28,
    lineHeight: 32,
    color: Colors.text,
    marginBottom: 8,
  },
  metaRow: {
    flexDirection: "row",
    flexWrap: "wrap",
    alignItems: "center",
    gap: 8,
    marginBottom: 8,
  },
  metaItem: { flexDirection: "row", alignItems: "center", gap: 4 },
  // Subdued meta row (rating • year • runtime).
  metaText: { fontFamily: "Inter_500Medium", fontSize: 13, color: "#C7CBD1" },
  metaDot: { fontFamily: "Inter_500Medium", fontSize: 13, color: "#6B7280" },
  pillRow: { flexDirection: "row", flexWrap: "wrap", gap: 6, marginBottom: 10 },
  genrePill: {
    backgroundColor: "rgba(255,255,255,0.10)",
    borderRadius: 999,
    paddingHorizontal: 10,
    paddingVertical: 3,
  },
  genreText: { fontFamily: "Inter_500Medium", fontSize: 11, color: "#E5E7EB" },
  overview: {
    fontFamily: "Inter_400Regular",
    fontSize: 15,
    lineHeight: 22,
    color: "#D1D5DB",
    marginBottom: 12,
  },
  includedPill: {
    flexDirection: "row",
    alignItems: "center",
    alignSelf: "flex-start",
    gap: 6,
    // More opaque so "Included with X" is clearly readable over artwork.
    backgroundColor: "rgba(5,7,10,0.85)",
    borderWidth: 1,
    borderColor: "rgba(34,197,94,0.4)",
    borderRadius: 999,
    paddingLeft: 8,
    paddingRight: 12,
    paddingVertical: 6,
  },
  includedText: { fontFamily: "Inter_600SemiBold", fontSize: 12, color: "#A7F3C0", flexShrink: 1 },
  providerRow: { flexDirection: "row", alignItems: "center", gap: 6, flexWrap: "wrap" },
  providerChip: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    backgroundColor: "rgba(5,7,10,0.8)",
    borderWidth: 1,
    borderColor: "rgba(255,255,255,0.14)",
    borderRadius: 8,
    paddingHorizontal: 8,
    paddingVertical: 4,
  },
  providerChipText: { fontFamily: "Inter_600SemiBold", fontSize: 12, color: "#E5E7EB", maxWidth: 120 },
});

export const SwipeCard = React.memo(SwipeCardImpl);
