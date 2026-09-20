/**
 * WatchedFeedbackSheet — a fast bottom sheet shown when the user marks a title
 * as "Watched" from the Discover deck (button or swipe up).
 *
 * Instead of posting the watched action immediately, we ask "What did you
 * think?" and capture a sentiment. One tap selects an option and reports back
 * via `onSelect`; Cancel dismisses without changing the card.
 *
 * Options map to the POST /user/action contract:
 *   Loved it        → { watched_sentiment: "loved",    completed: true }
 *   Liked it        → { watched_sentiment: "liked",    completed: true }
 *   It was okay     → { watched_sentiment: "neutral",  completed: true }
 *   Didn't like it  → { watched_sentiment: "disliked", completed: true }
 *   Haven't finished it → { completed: false } (sentiment omitted)
 */
import { Ionicons } from "@expo/vector-icons";
import React, { useEffect } from "react";
import { Modal, Pressable, StyleSheet, Text, View } from "react-native";
import Animated, {
  useAnimatedStyle,
  useSharedValue,
  withTiming,
} from "react-native-reanimated";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { Colors } from "@/constants/colors";
import type { WatchedMeta, WatchedSentiment } from "@/lib/discover-api";

interface Props {
  visible: boolean;
  title?: string;
  onSelect: (meta: WatchedMeta) => void;
  onCancel: () => void;
}

interface Option {
  key: string;
  label: string;
  icon: keyof typeof Ionicons.glyphMap;
  color: string;
  meta: WatchedMeta;
}

const OPTIONS: Option[] = [
  {
    key: "loved",
    label: "Loved it",
    icon: "heart",
    color: Colors.amber,
    meta: { watched_sentiment: "loved", completed: true },
  },
  {
    key: "liked",
    label: "Liked it",
    icon: "thumbs-up",
    color: Colors.success,
    meta: { watched_sentiment: "liked", completed: true },
  },
  {
    key: "neutral",
    label: "It was okay",
    icon: "remove-circle",
    color: Colors.textSecondary,
    meta: { watched_sentiment: "neutral", completed: true },
  },
  {
    key: "disliked",
    label: "Didn't like it",
    icon: "thumbs-down",
    color: Colors.danger,
    meta: { watched_sentiment: "disliked", completed: true },
  },
];

function WatchedFeedbackSheetImpl({ visible, title, onSelect, onCancel }: Props) {
  const insets = useSafeAreaInsets();
  const progress = useSharedValue(0);

  useEffect(() => {
    progress.value = withTiming(visible ? 1 : 0, { duration: 180 });
  }, [visible, progress]);

  const sheetStyle = useAnimatedStyle(() => ({
    transform: [{ translateY: (1 - progress.value) * 40 }],
    opacity: progress.value,
  }));

  return (
    <Modal
      visible={visible}
      transparent
      animationType="fade"
      onRequestClose={onCancel}
      statusBarTranslucent
    >
      <Pressable style={styles.backdrop} onPress={onCancel} accessibilityLabel="Dismiss" />
      <View style={styles.anchor} pointerEvents="box-none">
        <Animated.View
          style={[styles.sheet, { paddingBottom: Math.max(insets.bottom, 12) + 8 }, sheetStyle]}
          testID="watched-feedback-sheet"
        >
          <View style={styles.grabber} />
          <Text style={styles.title}>What did you think?</Text>
          {!!title && (
            <Text style={styles.subtitle} numberOfLines={1}>
              {title}
            </Text>
          )}

          <View style={styles.options}>
            {OPTIONS.map((opt) => (
              <Pressable
                key={opt.key}
                onPress={() => onSelect(opt.meta)}
                style={({ pressed }) => [styles.optionRow, pressed && styles.optionPressed]}
                accessibilityRole="button"
                accessibilityLabel={opt.label}
                testID={`watched-option-${opt.key}`}
              >
                <View style={[styles.optionIcon, { borderColor: opt.color }]}>
                  <Ionicons name={opt.icon} size={18} color={opt.color} />
                </View>
                <Text style={styles.optionLabel}>{opt.label}</Text>
                <Ionicons name="chevron-forward" size={16} color={Colors.textTertiary} />
              </Pressable>
            ))}

            <Pressable
              onPress={() => onSelect({ completed: false })}
              style={({ pressed }) => [styles.optionRow, pressed && styles.optionPressed]}
              accessibilityRole="button"
              accessibilityLabel="Haven't finished it"
              testID="watched-option-unfinished"
            >
              <View style={[styles.optionIcon, { borderColor: Colors.textTertiary }]}>
                <Ionicons name="time-outline" size={18} color={Colors.textSecondary} />
              </View>
              <Text style={styles.optionLabel}>Haven&apos;t finished it</Text>
              <Ionicons name="chevron-forward" size={16} color={Colors.textTertiary} />
            </Pressable>
          </View>

          <Pressable
            onPress={onCancel}
            style={({ pressed }) => [styles.cancelBtn, pressed && { opacity: 0.8 }]}
            accessibilityRole="button"
            accessibilityLabel="Cancel"
            testID="watched-cancel"
          >
            <Text style={styles.cancelText}>Cancel</Text>
          </Pressable>
        </Animated.View>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  backdrop: {
    ...StyleSheet.absoluteFillObject,
    backgroundColor: "rgba(0,0,0,0.6)",
  },
  anchor: {
    ...StyleSheet.absoluteFillObject,
    justifyContent: "flex-end",
  },
  sheet: {
    backgroundColor: Colors.velvet,
    borderTopLeftRadius: 28,
    borderTopRightRadius: 28,
    borderTopWidth: 1,
    borderColor: Colors.border,
    paddingHorizontal: 20,
    paddingTop: 12,
  },
  grabber: {
    alignSelf: "center",
    width: 40,
    height: 4,
    borderRadius: 2,
    backgroundColor: Colors.borderStrong,
    marginBottom: 16,
  },
  title: { fontFamily: "Inter_800ExtraBold", fontSize: 22, color: Colors.text },
  subtitle: {
    fontFamily: "Inter_500Medium",
    fontSize: 13,
    color: Colors.textSecondary,
    marginTop: 4,
  },
  options: { marginTop: 18, gap: 10 },
  optionRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 14,
    backgroundColor: Colors.surface,
    borderRadius: 16,
    borderWidth: 1,
    borderColor: Colors.border,
    paddingHorizontal: 14,
    paddingVertical: 14,
    minHeight: 44,
  },
  optionPressed: { opacity: 0.8, backgroundColor: Colors.surfaceLight },
  optionIcon: {
    width: 40,
    height: 40,
    borderRadius: 20,
    borderWidth: 1.5,
    backgroundColor: "rgba(255,255,255,0.03)",
    alignItems: "center",
    justifyContent: "center",
  },
  optionLabel: { flex: 1, fontFamily: "Inter_600SemiBold", fontSize: 16, color: Colors.text },
  cancelBtn: {
    marginTop: 14,
    alignItems: "center",
    justifyContent: "center",
    paddingVertical: 14,
    borderRadius: 16,
    backgroundColor: "rgba(255,255,255,0.04)",
    minHeight: 44,
  },
  cancelText: { fontFamily: "Inter_700Bold", fontSize: 15, color: Colors.textSecondary },
});

export const WatchedFeedbackSheet = React.memo(WatchedFeedbackSheetImpl);
