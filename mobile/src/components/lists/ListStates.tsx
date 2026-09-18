/**
 * Shared branded loading / empty / error state components for list screens.
 */
import { Ionicons } from "@expo/vector-icons";
import {
  ActivityIndicator,
  Pressable,
  StyleSheet,
  Text,
  View,
} from "react-native";

import { Colors } from "@/constants/colors";

export function ListLoading({ label }: { label?: string }) {
  return (
    <View style={styles.center} accessibilityRole="progressbar">
      <ActivityIndicator color={Colors.amber} size="large" />
      {label ? <Text style={styles.subtle}>{label}</Text> : null}
    </View>
  );
}

export function ListError({
  message,
  onRetry,
  testID,
}: {
  message?: string;
  onRetry: () => void;
  testID?: string;
}) {
  return (
    <View style={styles.center} testID={testID}>
      <View style={styles.iconWrap}>
        <Ionicons name="cloud-offline-outline" size={26} color={Colors.amber} />
      </View>
      <Text style={styles.title}>Something went wrong</Text>
      <Text style={styles.subtle}>
        {message || "Couldn't load. Check your connection and try again."}
      </Text>
      <Pressable
        onPress={onRetry}
        style={({ pressed }) => [styles.retryBtn, pressed && { opacity: 0.85 }]}
        accessibilityRole="button"
        accessibilityLabel="Try again"
        testID={testID ? `${testID}-retry` : undefined}
      >
        <Text style={styles.retryText}>Try again</Text>
      </Pressable>
    </View>
  );
}

export function ListEmpty({
  icon = "sparkles-outline",
  title,
  body,
  action,
}: {
  icon?: keyof typeof Ionicons.glyphMap;
  title: string;
  body?: string;
  action?: { label: string; onPress: () => void };
}) {
  return (
    <View style={styles.center}>
      <View style={styles.iconWrap}>
        <Ionicons name={icon} size={26} color={Colors.amber} />
      </View>
      <Text style={styles.title}>{title}</Text>
      {body ? <Text style={styles.subtle}>{body}</Text> : null}
      {action ? (
        <Pressable
          onPress={action.onPress}
          style={({ pressed }) => [styles.retryBtn, pressed && { opacity: 0.85 }]}
          accessibilityRole="button"
          accessibilityLabel={action.label}
        >
          <Text style={styles.retryText}>{action.label}</Text>
        </Pressable>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  center: {
    alignItems: "center",
    justifyContent: "center",
    paddingVertical: 64,
    paddingHorizontal: 24,
    gap: 10,
  },
  iconWrap: {
    width: 56,
    height: 56,
    borderRadius: 18,
    backgroundColor: "rgba(255,122,24,0.15)",
    alignItems: "center",
    justifyContent: "center",
    marginBottom: 4,
  },
  title: {
    fontFamily: "Inter_700Bold",
    fontSize: 18,
    color: Colors.text,
    textAlign: "center",
  },
  subtle: {
    fontFamily: "Inter_400Regular",
    fontSize: 13,
    color: Colors.textSecondary,
    textAlign: "center",
    lineHeight: 19,
  },
  retryBtn: {
    marginTop: 8,
    backgroundColor: Colors.amber,
    borderRadius: 14,
    paddingHorizontal: 20,
    paddingVertical: 12,
  },
  retryText: {
    fontFamily: "Inter_700Bold",
    fontSize: 14,
    color: "#0B0500",
  },
});
