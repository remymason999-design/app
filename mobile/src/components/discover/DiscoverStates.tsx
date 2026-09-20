/**
 * Branded loading / empty / error states for the Discover deck.
 */
import { Ionicons } from "@expo/vector-icons";
import React from "react";
import { ActivityIndicator, Pressable, StyleSheet, Text, View } from "react-native";

import { Colors } from "@/constants/colors";

export function CardSkeleton() {
  return (
    <View style={styles.skeleton} testID="discover-skeleton">
      <View style={styles.skeletonInfo}>
        <View style={styles.skeletonPills}>
          <View style={[styles.pill, { width: 56 }]} />
          <View style={[styles.pill, { width: 80 }]} />
        </View>
        <View style={[styles.bar, { width: "80%", height: 30 }]} />
        <View style={[styles.bar, { width: "50%", height: 16 }]} />
        <View style={[styles.bar, { width: "100%", height: 12 }]} />
        <View style={[styles.bar, { width: "75%", height: 12 }]} />
      </View>
      <ActivityIndicator color={Colors.amber} style={styles.spinner} />
    </View>
  );
}

export function ErrorState({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <View style={styles.center} testID="discover-error">
      <View style={styles.iconWrap}>
        <Ionicons name="cloud-offline-outline" size={30} color={Colors.amber} />
      </View>
      <Text style={styles.title}>Couldn&apos;t load Discover</Text>
      <Text style={styles.body}>{message}</Text>
      <Pressable
        onPress={onRetry}
        style={({ pressed }) => [styles.primaryBtn, pressed && { opacity: 0.85 }]}
        accessibilityRole="button"
        accessibilityLabel="Retry loading Discover"
        testID="discover-retry"
      >
        <Text style={styles.primaryBtnText}>Try again</Text>
      </Pressable>
    </View>
  );
}

export function EmptyState({ onReload }: { onReload: () => void }) {
  return (
    <View style={styles.center} testID="discover-empty">
      <View style={styles.iconWrap}>
        <Ionicons name="sparkles" size={28} color={Colors.amber} />
      </View>
      <Text style={styles.title}>You&apos;re all caught up</Text>
      <Text style={styles.body}>
        You&apos;ve seen everything in this tab. Try a different one or refresh your picks.
      </Text>
      <Pressable
        onPress={onReload}
        style={({ pressed }) => [styles.primaryBtn, pressed && { opacity: 0.85 }]}
        accessibilityRole="button"
        accessibilityLabel="Refresh picks"
        testID="discover-refresh"
      >
        <Text style={styles.primaryBtnText}>Refresh picks</Text>
      </Pressable>
    </View>
  );
}

const styles = StyleSheet.create({
  skeleton: {
    ...StyleSheet.absoluteFillObject,
    borderRadius: 24,
    overflow: "hidden",
    backgroundColor: Colors.velvet,
  },
  spinner: { position: "absolute", top: "42%", alignSelf: "center" },
  skeletonInfo: { position: "absolute", left: 0, right: 0, bottom: 0, padding: 24, gap: 12 },
  skeletonPills: { flexDirection: "row", gap: 6 },
  pill: { height: 20, borderRadius: 999, backgroundColor: "rgba(255,255,255,0.1)" },
  bar: { borderRadius: 8, backgroundColor: "rgba(255,255,255,0.12)" },
  center: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
    paddingHorizontal: 32,
  },
  iconWrap: {
    width: 64,
    height: 64,
    borderRadius: 18,
    backgroundColor: "rgba(255,122,24,0.15)",
    borderWidth: 1,
    borderColor: "rgba(255,122,24,0.2)",
    alignItems: "center",
    justifyContent: "center",
    marginBottom: 16,
  },
  title: { fontFamily: "Inter_700Bold", fontSize: 19, color: Colors.text, marginBottom: 8, textAlign: "center" },
  body: {
    fontFamily: "Inter_400Regular",
    fontSize: 14,
    color: Colors.textSecondary,
    textAlign: "center",
    lineHeight: 21,
    marginBottom: 24,
  },
  primaryBtn: {
    backgroundColor: Colors.amber,
    borderRadius: 16,
    paddingHorizontal: 24,
    paddingVertical: 13,
  },
  primaryBtnText: { fontFamily: "Inter_700Bold", fontSize: 15, color: "#0B0500" },
});
