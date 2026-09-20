/**
 * InlineNotice — a small toast-like banner shown near the bottom of the deck
 * when an action fails (e.g. a swipe's POST /user/action could not be recorded).
 * Auto-dismisses after a few seconds.
 */
import { Ionicons } from "@expo/vector-icons";
import React, { useEffect } from "react";
import { StyleSheet, Text } from "react-native";
import Animated, { FadeInDown, FadeOutDown } from "react-native-reanimated";

import { Colors } from "@/constants/colors";

interface Props {
  message: string | null;
  onHide: () => void;
}

function InlineNoticeImpl({ message, onHide }: Props) {
  useEffect(() => {
    if (!message) return;
    const t = setTimeout(onHide, 3200);
    return () => clearTimeout(t);
  }, [message, onHide]);

  if (!message) return null;

  return (
    <Animated.View
      entering={FadeInDown}
      exiting={FadeOutDown}
      style={styles.notice}
      accessibilityLiveRegion="polite"
      testID="discover-notice"
    >
      <Ionicons name="alert-circle" size={16} color={Colors.amber} />
      <Text style={styles.text}>{message}</Text>
    </Animated.View>
  );
}

const styles = StyleSheet.create({
  notice: {
    position: "absolute",
    left: 16,
    right: 16,
    bottom: 12,
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    backgroundColor: "rgba(17,24,39,0.96)",
    borderWidth: 1,
    borderColor: "rgba(255,122,24,0.4)",
    borderRadius: 12,
    paddingHorizontal: 12,
    paddingVertical: 10,
  },
  text: { flex: 1, fontFamily: "Inter_500Medium", fontSize: 13, color: Colors.text },
});

export const InlineNotice = React.memo(InlineNoticeImpl);
