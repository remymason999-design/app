/**
 * Toast — a tiny transient confirmation shown after an action (e.g. after
 * capturing "Watched" feedback). Auto-hides after a short delay.
 */
import { Ionicons } from "@expo/vector-icons";
import React, { useEffect } from "react";
import { StyleSheet, Text } from "react-native";
import Animated, {
  useAnimatedStyle,
  useSharedValue,
  withTiming,
} from "react-native-reanimated";

import { Colors } from "@/constants/colors";

interface Props {
  message: string | null;
  onHide: () => void;
  /** ms the toast stays visible before auto-hiding. */
  duration?: number;
}

function ToastImpl({ message, onHide, duration = 1400 }: Props) {
  const progress = useSharedValue(0);

  useEffect(() => {
    if (!message) return;
    progress.value = withTiming(1, { duration: 160 });
    const t = setTimeout(() => {
      progress.value = withTiming(0, { duration: 220 });
      const done = setTimeout(onHide, 240);
      return () => clearTimeout(done);
    }, duration);
    return () => clearTimeout(t);
  }, [message, duration, onHide, progress]);

  const style = useAnimatedStyle(() => ({
    opacity: progress.value,
    transform: [{ translateY: (1 - progress.value) * 10 }],
  }));

  if (!message) return null;

  return (
    <Animated.View style={[styles.toast, style]} pointerEvents="none" testID="discover-toast">
      <Ionicons name="checkmark-circle" size={16} color={Colors.success} />
      <Text style={styles.text}>{message}</Text>
    </Animated.View>
  );
}

const styles = StyleSheet.create({
  toast: {
    position: "absolute",
    alignSelf: "center",
    bottom: 16,
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    backgroundColor: "rgba(11,17,26,0.96)",
    borderWidth: 1,
    borderColor: Colors.border,
    borderRadius: 999,
    paddingHorizontal: 16,
    paddingVertical: 10,
    zIndex: 50,
  },
  text: { fontFamily: "Inter_600SemiBold", fontSize: 13, color: Colors.text },
});

export const Toast = React.memo(ToastImpl);
