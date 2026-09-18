import { Ionicons } from "@expo/vector-icons";
import * as Haptics from "expo-haptics";
import { router } from "expo-router";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
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
import { fetchGenres, updatePreferences } from "@/lib/onboarding-api";

export default function OnboardingGenres() {
  const { user, setUser } = useAuth();
  const insets = useSafeAreaInsets();
  const [selected, setSelected] = useState<Set<string>>(
    () => new Set((user?.genres as string[]) || [])
  );
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const query = useQuery<string[]>({ queryKey: ["/genres"], queryFn: fetchGenres });
  const genres = query.data ?? [];

  const toggle = (g: string) => {
    Haptics.selectionAsync();
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(g)) next.delete(g);
      else next.add(g);
      return next;
    });
  };

  const proceed = async () => {
    if (saving) return;
    setSaving(true);
    setError(null);
    try {
      {
        const updated = await updatePreferences({ genres: Array.from(selected) });
        setUser(updated);
      }
      router.push("/onboarding/preferences");
    } catch (e) {
      Haptics.notificationAsync(Haptics.NotificationFeedbackType.Error);
      setError(getFriendlyMessage(e));
    } finally {
      setSaving(false);
    }
  };

  const skip = () => {
    if (saving) return;
    router.push("/onboarding/preferences");
  };

  return (
    <View style={styles.root}>
      <ScrollView
        contentContainerStyle={[
          styles.content,
          { paddingTop: insets.top + 20, paddingBottom: 160 },
        ]}
        keyboardShouldPersistTaps="handled"
      >
        <OnboardingProgress step={2} />
        <Text style={styles.eyebrow}>Step 2 of 4</Text>
        <Text style={styles.h1}>What do you love watching?</Text>
        <Text style={styles.sub}>Pick a few — we&apos;ll learn the rest from your swipes.</Text>

        {query.isLoading ? (
          <View style={styles.center}>
            <ActivityIndicator color={Colors.amber} />
          </View>
        ) : query.isError ? (
          <View style={styles.center}>
            <Text style={styles.errorText}>Couldn&apos;t load genres.</Text>
            <Pressable
              onPress={() => query.refetch()}
              style={styles.retryBtn}
              accessibilityRole="button"
              accessibilityLabel="Retry loading genres"
            >
              <Text style={styles.retryText}>Retry</Text>
            </Pressable>
          </View>
        ) : (
          <View style={styles.chips}>
            {genres.map((g) => {
              const on = selected.has(g);
              return (
                <Pressable
                  key={g}
                  onPress={() => toggle(g)}
                  style={[styles.chip, on && styles.chipOn]}
                  accessibilityRole="button"
                  accessibilityState={{ selected: on }}
                  accessibilityLabel={g}
                >
                  <Text style={[styles.chipText, on && styles.chipTextOn]}>{g}</Text>
                </Pressable>
              );
            })}
          </View>
        )}

        {error ? <Text style={[styles.errorText, { marginTop: 16 }]}>{error}</Text> : null}
      </ScrollView>

      <View style={[styles.bottomBar, { paddingBottom: insets.bottom + 16 }]}>
        <Pressable
          onPress={() => router.back()}
          style={styles.backBtn}
          accessibilityRole="button"
          accessibilityLabel="Back"
          disabled={saving}
        >
          <Ionicons name="arrow-back" size={18} color={Colors.textSecondary} />
        </Pressable>

        <Text style={styles.count}>{selected.size} selected</Text>

        <Pressable
          onPress={skip}
          style={styles.skipBtn}
          accessibilityRole="button"
          accessibilityLabel="Skip"
          disabled={saving}
        >
          <Text style={styles.skipText}>Skip</Text>
        </Pressable>

        <Pressable
          onPress={proceed}
          disabled={saving}
          style={[styles.primaryBtn, saving && styles.btnDisabled]}
          accessibilityRole="button"
          accessibilityLabel="Continue"
        >
          {saving ? (
            <ActivityIndicator color="#0B0500" />
          ) : (
            <Text style={styles.primaryBtnText}>Continue</Text>
          )}
        </Pressable>
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
    marginBottom: 24,
    lineHeight: 21,
  },
  center: { alignItems: "center", justifyContent: "center", paddingVertical: 48, gap: 14 },
  chips: { flexDirection: "row", flexWrap: "wrap", gap: 10 },
  chip: {
    paddingHorizontal: 16,
    paddingVertical: 10,
    borderRadius: 999,
    borderWidth: 1,
    borderColor: Colors.borderStrong,
    backgroundColor: "rgba(255,255,255,0.02)",
  },
  chipOn: { backgroundColor: Colors.amber, borderColor: Colors.amber },
  chipText: { fontFamily: "Inter_500Medium", fontSize: 14, color: Colors.textSecondary },
  chipTextOn: { color: "#0B0500", fontFamily: "Inter_600SemiBold" },
  bottomBar: {
    position: "absolute",
    left: 0,
    right: 0,
    bottom: 0,
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
    paddingHorizontal: 20,
    paddingTop: 14,
    backgroundColor: Colors.velvet,
    borderTopWidth: 1,
    borderTopColor: Colors.border,
  },
  backBtn: {
    width: 44,
    height: 44,
    borderRadius: 14,
    borderWidth: 1,
    borderColor: Colors.border,
    alignItems: "center",
    justifyContent: "center",
  },
  count: {
    flex: 1,
    fontFamily: "Inter_500Medium",
    fontSize: 13,
    color: Colors.textSecondary,
  },
  skipBtn: { paddingHorizontal: 8, paddingVertical: 10 },
  skipText: { fontFamily: "Inter_500Medium", fontSize: 14, color: Colors.textSecondary },
  primaryBtn: {
    backgroundColor: Colors.amber,
    paddingHorizontal: 22,
    paddingVertical: 14,
    borderRadius: 16,
    minWidth: 110,
    alignItems: "center",
    justifyContent: "center",
  },
  primaryBtnText: { fontFamily: "Inter_700Bold", fontSize: 15, color: "#0B0500" },
  btnDisabled: { opacity: 0.6 },
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
