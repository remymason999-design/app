/**
 * Poster card used in the Watchlist and Compare grids.
 */
import { Ionicons } from "@expo/vector-icons";
import { Image } from "expo-image";
import { Pressable, StyleSheet, Text, View } from "react-native";

import { Colors } from "@/constants/colors";

export interface PosterCardProps {
  title: string;
  posterUrl?: string | null;
  rating?: number | null;
  subLabel?: string | null;
  sentiment?: "loved" | "liked" | "disliked" | "neutral" | string | null;
  reactionBanner?: { symbol: string; label: string; who: string } | null;
  progressPct?: number | null;
  /** Optional server-derived progress copy shown alongside the title metadata. */
  progressLabel?: string | null;
  /** Render website-style title and metadata over the poster. */
  overlayMetadata?: boolean;
  onPress: () => void;
  width: number;
  testID?: string;
}

export function PosterCard({
  title,
  posterUrl,
  rating,
  subLabel,
  sentiment,
  reactionBanner,
  progressPct,
  progressLabel,
  overlayMetadata = false,
  onPress,
  width,
  testID,
}: PosterCardProps) {
  const height = Math.round((width * 3) / 2);
  const sentimentLabel =
    sentiment === "neutral" ? "Okay"
      : sentiment === "disliked" ? "Didn't like"
        : sentiment === "loved" ? "Loved"
          : sentiment === "liked" ? "Liked"
            : sentiment?.replace("_", " ");
  return (
    <Pressable
      onPress={onPress}
      style={({ pressed }) => [{ width }, pressed && { opacity: 0.85 }]}
      accessibilityRole="button"
      accessibilityLabel={`Open details for ${title}`}
      testID={testID}
    >
      <View style={[styles.poster, { width, height }]}>
        {posterUrl ? (
          <Image
            source={{ uri: posterUrl }}
            style={StyleSheet.absoluteFill}
            contentFit="cover"
            transition={200}
          />
        ) : (
          <View style={styles.posterFallback}>
            <Ionicons name="film-outline" size={22} color={Colors.textTertiary} />
          </View>
        )}
        {reactionBanner && (
          <View style={styles.reactionBanner} testID={`${testID}-reaction-banner`}>
            <Text style={styles.reactionBannerText}>
              {reactionBanner.symbol} {reactionBanner.who} {reactionBanner.label}
            </Text>
          </View>
        )}
        {progressPct != null && !overlayMetadata && (
          <View style={styles.progressTrack}>
            <View style={[styles.progressFill, { width: `${progressPct}%` }]} />
          </View>
        )}
        {overlayMetadata && (
          <View style={styles.overlayMeta}>
            <Text style={styles.overlayTitle} numberOfLines={2}>{title}</Text>
            <View style={styles.overlayRow}>
              {sentiment ? (
                <View style={styles.ratingRow}>
                  {sentiment === "loved" && <Ionicons name="heart" size={11} color={Colors.amber} />}
                  {sentiment === "liked" && <Ionicons name="thumbs-up" size={11} color={Colors.amber} />}
                  {sentiment === "disliked" && <Ionicons name="thumbs-down" size={11} color={Colors.danger} />}
                  {sentiment === "neutral" && <Ionicons name="remove-circle-outline" size={11} color={Colors.textSecondary} />}
                  <Text style={styles.overlayText}>{sentimentLabel}</Text>
                </View>
              ) : rating != null ? (
                <View style={styles.ratingRow}>
                  <Ionicons name="star" size={11} color={Colors.amber} />
                  <Text style={styles.overlayText}>{rating.toFixed(1)}</Text>
                </View>
              ) : <View />}
              {subLabel ? <Text style={styles.overlayText}>{subLabel}</Text> : null}
            </View>
            {progressPct != null ? (
              <View style={styles.overlayProgressBlock}>
                {progressLabel ? <Text style={styles.overlayProgress}>{progressLabel}</Text> : null}
                <View
                  style={styles.overlayProgressTrack}
                  accessibilityRole="progressbar"
                  accessibilityValue={{ min: 0, max: 100, now: progressPct }}
                >
                  <View style={[styles.overlayProgressFill, { width: `${progressPct}%` }]} />
                </View>
              </View>
            ) : progressLabel ? (
              <Text style={styles.overlayProgress}>{progressLabel}</Text>
            ) : null}
          </View>
        )}
      </View>
      {!overlayMetadata && (
        <>
          <Text style={styles.title} numberOfLines={2}>
            {title}
          </Text>
          <View style={styles.metaRow}>
            <View style={styles.leftMeta}>
              {sentiment === "loved" && <Ionicons name="heart" size={13} color={Colors.amber} />}
              {sentiment === "liked" && <Ionicons name="thumbs-up" size={13} color={Colors.amber} />}
              {sentiment === "disliked" && <Ionicons name="thumbs-down" size={13} color={Colors.danger} />}
              {sentiment ? <Text style={styles.sentiment}>{sentimentLabel}</Text> : null}
              {(!sentiment && rating != null) ? (
                <View style={styles.ratingRow}>
                  <Ionicons name="star" size={11} color={Colors.amber} />
                  <Text style={styles.rating}>{rating.toFixed(1)}</Text>
                </View>
              ) : null}
            </View>
            {subLabel ? <Text style={styles.sub}>{subLabel}</Text> : null}
          </View>
          {progressLabel ? <Text style={styles.progressLabel}>{progressLabel}</Text> : null}
        </>
      )}
    </Pressable>
  );
}

const styles = StyleSheet.create({
  poster: {
    borderRadius: 16,
    overflow: "hidden",
    backgroundColor: Colors.surface,
  },
  posterFallback: {
    position: "absolute",
    top: 0,
    left: 0,
    right: 0,
    bottom: 0,
    alignItems: "center",
    justifyContent: "center",
  },
  title: {
    fontFamily: "Inter_600SemiBold",
    fontSize: 13,
    color: Colors.text,
    marginTop: 7,
    lineHeight: 17,
  },
  metaRow: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    marginTop: 3,
  },
  leftMeta: { flexDirection: "row", alignItems: "center", gap: 4 },
  sentiment: {
    fontFamily: "Inter_500Medium",
    fontSize: 10,
    color: Colors.textSecondary,
    textTransform: "capitalize",
  },
  ratingRow: { flexDirection: "row", alignItems: "center", gap: 3 },
  rating: {
    fontFamily: "Inter_500Medium",
    fontSize: 11,
    color: Colors.textSecondary,
  },
  sub: {
    fontFamily: "Inter_400Regular",
    fontSize: 10,
    color: Colors.textTertiary,
  },
  progressLabel: {
    fontFamily: "Inter_500Medium",
    fontSize: 10,
    lineHeight: 14,
    color: Colors.amber,
    marginTop: 3,
  },
  progressTrack: {
    position: "absolute",
    bottom: 0,
    left: 0,
    right: 0,
    height: 4,
    backgroundColor: "rgba(255,255,255,0.2)",
  },
  progressFill: {
    height: "100%",
    backgroundColor: Colors.amber,
  },
  overlayProgressBlock: {
    marginTop: 7,
    gap: 5,
  },
  overlayProgressTrack: {
    width: "100%",
    height: 6,
    overflow: "hidden",
    borderRadius: 999,
    backgroundColor: "rgba(255,255,255,0.25)",
  },
  overlayProgressFill: {
    height: "100%",
    borderRadius: 999,
    backgroundColor: Colors.amber,
  },
  reactionBanner: {
    position: "absolute",
    bottom: 0,
    left: 0,
    right: 0,
    backgroundColor: "rgba(0,0,0,0.85)",
    borderTopWidth: 1,
    borderColor: "rgba(255,255,255,0.15)",
    paddingHorizontal: 6,
    paddingVertical: 6,
  },
  reactionBannerText: {
    fontFamily: "Inter_500Medium",
    fontSize: 10,
    color: "#fff",
    lineHeight: 12,
  },
  overlayMeta: {
    position: "absolute",
    left: 0,
    right: 0,
    bottom: 4,
    paddingTop: 28,
    paddingHorizontal: 12,
    paddingBottom: 10,
    backgroundColor: "rgba(4,5,8,0.76)",
  },
  overlayTitle: {
    fontFamily: "Inter_700Bold",
    fontSize: 13,
    lineHeight: 17,
    color: Colors.text,
  },
  overlayRow: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    marginTop: 4,
  },
  overlayText: {
    fontFamily: "Inter_500Medium",
    fontSize: 10,
    color: Colors.textSecondary,
  },
  overlayProgress: {
    fontFamily: "Inter_500Medium",
    fontSize: 10,
    color: Colors.amber,
    marginTop: 3,
  },
});
