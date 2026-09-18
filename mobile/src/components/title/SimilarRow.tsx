import { Ionicons } from "@expo/vector-icons";
import { Image, Pressable, ScrollView, StyleSheet, Text, View } from "react-native";

import { Colors } from "@/constants/colors";
import type { SimilarItem } from "@/lib/content-api";

const POSTER_W = 120;
const CARD_GAP = 12;

interface Props {
  items: SimilarItem[];
  onPress: (item: SimilarItem) => void;
}

/** Horizontal "More like this" rail — tap pushes another title screen. */
export function SimilarRow({ items, onPress }: Props) {
  if (!items.length) return null;
  return (
    <View style={styles.wrap}>
      <Text style={styles.heading}>More like this</Text>
      <ScrollView
        horizontal
        showsHorizontalScrollIndicator={false}
        contentContainerStyle={styles.scroll}
        decelerationRate="fast"
        snapToInterval={POSTER_W + CARD_GAP}
        snapToAlignment="start"
      >
        {items.map((m) => (
          <Pressable
            key={m.id}
            onPress={() => onPress(m)}
            style={({ pressed }) => [styles.card, pressed && { opacity: 0.7 }]}
            accessibilityRole="button"
            accessibilityLabel={`Open ${m.title || "title"}`}
          >
            <View style={styles.posterWrap}>
              {m.poster_url ? (
                <Image source={{ uri: m.poster_url }} style={styles.poster} resizeMode="cover" />
              ) : (
                <View style={[styles.poster, styles.posterFallback]}>
                  <Ionicons name="film-outline" size={22} color={Colors.textTertiary} />
                </View>
              )}
            </View>
            <Text style={styles.title} numberOfLines={2}>
              {m.title || "Untitled"}
            </Text>
            {typeof m.rating === "number" && m.rating > 0 ? (
              <View style={styles.ratingRow}>
                <Ionicons name="star" size={10} color={Colors.amber} />
                <Text style={styles.rating}>{m.rating.toFixed(1)}</Text>
              </View>
            ) : null}
          </Pressable>
        ))}
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { marginTop: 24 },
  heading: {
    fontFamily: "Inter_700Bold",
    fontSize: 17,
    color: Colors.text,
    marginBottom: 12,
    paddingHorizontal: 20,
  },
  scroll: { paddingHorizontal: 20, gap: CARD_GAP },
  card: { width: POSTER_W },
  posterWrap: {
    width: POSTER_W,
    aspectRatio: 2 / 3,
    borderRadius: 12,
    overflow: "hidden",
    backgroundColor: Colors.velvet,
    marginBottom: 8,
  },
  poster: { width: "100%", height: "100%" },
  posterFallback: { alignItems: "center", justifyContent: "center" },
  title: {
    fontFamily: "Inter_600SemiBold",
    fontSize: 13,
    color: Colors.text,
    lineHeight: 17,
    minHeight: 34,
  },
  ratingRow: { flexDirection: "row", alignItems: "center", gap: 3, marginTop: 3 },
  rating: { fontFamily: "Inter_500Medium", fontSize: 11, color: Colors.textSecondary },
});
