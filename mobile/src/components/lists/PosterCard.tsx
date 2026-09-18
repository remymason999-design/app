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
  onPress,
  width,
  testID,
}: PosterCardProps) {
  const height = Math.round((width * 3) / 2);
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
        {progressPct != null && progressPct > 0 && progressPct < 100 && (
          <View style={styles.progressTrack}>
            <View style={[styles.progressFill, { width: `${progressPct}%` }]} />
          </View>
        )}
      </View>
      <Text style={styles.title} numberOfLines={2}>
        {title}
      </Text>
      <View style={styles.metaRow}>
        <View style={styles.leftMeta}>
          {sentiment === "loved" && <Ionicons name="heart" size={13} color={Colors.amber} />}
          {sentiment === "liked" && <Ionicons name="thumbs-up" size={13} color={Colors.amber} />}
          {sentiment === "disliked" && <Ionicons name="thumbs-down" size={13} color={Colors.danger} />}
          {sentiment ? <Text style={styles.sentiment}>{sentiment.replace("_", " ")}</Text> : null}
          {(!sentiment && rating != null) ? (
            <View style={styles.ratingRow}>
              <Ionicons name="star" size={11} color={Colors.amber} />
              <Text style={styles.rating}>{rating.toFixed(1)}</Text>
            </View>
          ) : null}
        </View>
        {subLabel ? <Text style={styles.sub}>{subLabel}</Text> : null}
      </View>
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
});
