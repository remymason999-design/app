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
  Switch,
  Text,
  View,
} from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { OnboardingProgress } from "@/components/onboarding/OnboardingProgress";
import { Colors } from "@/constants/colors";
import { useAuth } from "@/context/AuthContext";
import { getFriendlyMessage } from "@/lib/api";
import {
  ContentType,
  EXCLUDE_CATEGORIES,
  MOODS,
  fetchGenres,
  updatePreferences,
} from "@/lib/onboarding-api";
import { analytics, EVENTS } from "@/lib/analytics";

const CONTENT_OPTIONS: { id: ContentType; label: string; icon: keyof typeof Ionicons.glyphMap }[] = [
  { id: "both", label: "Both", icon: "layers-outline" },
  { id: "movie", label: "Films", icon: "film-outline" },
  { id: "tv", label: "TV Shows", icon: "tv-outline" },
];

function asStringArray(v: unknown): string[] {
  return Array.isArray(v) ? (v.filter((x) => typeof x === "string") as string[]) : [];
}

export default function OnboardingPreferences() {
  const { user, setUser } = useAuth();
  const insets = useSafeAreaInsets();

  const [contentType, setContentType] = useState<ContentType>(() => {
    const ct = user?.content_type;
    return ct === "movie" || ct === "tv" ? ct : "both";
  });
  const [excludedCats, setExcludedCats] = useState<Set<string>>(
    () => new Set(asStringArray(user?.excluded_categories))
  );
  const [moods, setMoods] = useState<Set<string>>(
    () => new Set(asStringArray(user?.moods))
  );
  const [excludedGenres, setExcludedGenres] = useState<Set<string>>(
    () => new Set(asStringArray(user?.excluded_genres))
  );
  const [genresOpen, setGenresOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const genresQuery = useQuery<string[]>({ queryKey: ["/genres"], queryFn: fetchGenres });
  const genres = genresQuery.data ?? [];

  const toggleSet = (
    setter: React.Dispatch<React.SetStateAction<Set<string>>>,
    value: string
  ) => {
    Haptics.selectionAsync();
    setter((prev) => {
      const next = new Set(prev);
      if (next.has(value)) next.delete(value);
      else next.add(value);
      return next;
    });
  };

  const toggleCategory = (id: string) => {
    Haptics.selectionAsync();
    setExcludedCats((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const save = async () => {
    if (saving) return;
    setSaving(true);
    setError(null);
    try {
      const updated = await updatePreferences({
        content_type: contentType,
        excluded_categories: Array.from(excludedCats),
        moods: Array.from(moods),
        excluded_genres: Array.from(excludedGenres),
      });
      setUser(updated);
      analytics.capture(EVENTS.ONBOARDING_STEP_COMPLETED, {
        step: "preferences",
        content_type: contentType,
        mood_count: moods.size,
        excluded_genre_count: excludedGenres.size,
      }, { user: updated });
      router.push("/onboarding/taste");
    } catch (e) {
      Haptics.notificationAsync(Haptics.NotificationFeedbackType.Error);
      setError(getFriendlyMessage(e));
    } finally {
      setSaving(false);
    }
  };

  const skip = () => {
    if (saving) return;
    router.push("/onboarding/taste");
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
        <OnboardingProgress step={3} />
        <Text style={styles.eyebrow}>Step 3 of 4</Text>
        <Text style={styles.h1}>Fine-tune your feed</Text>
        <Text style={styles.sub}>
          Filter the noise and set the mood. You can change all of this later.
        </Text>

        {/* Content type */}
        <Text style={styles.sectionLabel}>Content type</Text>
        <View style={styles.segmented}>
          {CONTENT_OPTIONS.map((o) => {
            const on = contentType === o.id;
            return (
              <Pressable
                key={o.id}
                onPress={() => {
                  Haptics.selectionAsync();
                  setContentType(o.id);
                }}
                style={[styles.segBtn, on && styles.segBtnOn]}
                accessibilityRole="button"
                accessibilityState={{ selected: on }}
                accessibilityLabel={o.label}
              >
                <Ionicons
                  name={o.icon}
                  size={18}
                  color={on ? "#0B0500" : Colors.textSecondary}
                />
                <Text style={[styles.segText, on && styles.segTextOn]}>{o.label}</Text>
              </Pressable>
            );
          })}
        </View>

        {/* Categories to hide */}
        <Text style={[styles.sectionLabel, styles.sectionSpacing]}>Categories to hide</Text>
        <View style={styles.toggleList}>
          {EXCLUDE_CATEGORIES.map((c) => {
            const on = excludedCats.has(c.id);
            return (
              <View key={c.id} style={[styles.toggleRow, on && styles.toggleRowOn]}>
                <View style={{ flex: 1 }}>
                  <Text style={styles.toggleTitle}>{c.label}</Text>
                  <Text style={styles.toggleDesc}>{c.description}</Text>
                </View>
                <Switch
                  value={on}
                  onValueChange={() => toggleCategory(c.id)}
                  trackColor={{ false: Colors.surfaceLight, true: Colors.amber }}
                  thumbColor="#FFFFFF"
                  accessibilityLabel={`Hide ${c.label}`}
                />
              </View>
            );
          })}
        </View>

        {/* Moods */}
        <Text style={[styles.sectionLabel, styles.sectionSpacing]}>Mood</Text>
        <View style={styles.chips}>
          {MOODS.map((m) => {
            const on = moods.has(m.id);
            return (
              <Pressable
                key={m.id}
                onPress={() => toggleSet(setMoods, m.id)}
                style={[styles.chip, on && styles.chipOn]}
                accessibilityRole="button"
                accessibilityState={{ selected: on }}
                accessibilityLabel={m.label}
              >
                <Text style={[styles.chipText, on && styles.chipTextOn]}>{m.label}</Text>
              </Pressable>
            );
          })}
        </View>

        {/* Genres to hide (collapsible) */}
        <Pressable
          onPress={() => {
            Haptics.selectionAsync();
            setGenresOpen((v) => !v);
          }}
          style={[styles.sectionLabelRow, styles.sectionSpacing]}
          accessibilityRole="button"
          accessibilityState={{ expanded: genresOpen }}
          accessibilityLabel="Genres to hide (optional)"
        >
          <Text style={styles.sectionLabel}>
            Genres to hide (optional)
            {excludedGenres.size > 0 ? `  ·  ${excludedGenres.size}` : ""}
          </Text>
          <Ionicons
            name={genresOpen ? "chevron-up" : "chevron-down"}
            size={16}
            color={Colors.textTertiary}
          />
        </Pressable>

        {genresOpen ? (
          genresQuery.isLoading ? (
            <View style={styles.center}>
              <ActivityIndicator color={Colors.amber} />
            </View>
          ) : genresQuery.isError ? (
            <Text style={styles.errorText}>Couldn&apos;t load genres.</Text>
          ) : (
            <View style={styles.chips}>
              {genres.map((g) => {
                const on = excludedGenres.has(g);
                return (
                  <Pressable
                    key={g}
                    onPress={() => toggleSet(setExcludedGenres, g)}
                    style={[styles.chip, on && styles.chipDangerOn]}
                    accessibilityRole="button"
                    accessibilityState={{ selected: on }}
                    accessibilityLabel={`Hide ${g}`}
                  >
                    {on ? (
                      <Ionicons
                        name="close"
                        size={12}
                        color="#FCA5A5"
                        style={{ marginRight: 4 }}
                      />
                    ) : null}
                    <Text style={[styles.chipText, on && styles.chipDangerText]}>{g}</Text>
                  </Pressable>
                );
              })}
            </View>
          )
        ) : null}

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

        <View style={{ flex: 1 }} />

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
          onPress={save}
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
  sectionLabel: {
    fontFamily: "Inter_600SemiBold",
    fontSize: 11,
    letterSpacing: 1.5,
    textTransform: "uppercase",
    color: Colors.textTertiary,
    marginBottom: 12,
  },
  sectionLabelRow: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
  },
  sectionSpacing: { marginTop: 28 },
  segmented: {
    flexDirection: "row",
    gap: 6,
    backgroundColor: "rgba(255,255,255,0.03)",
    borderRadius: 16,
    borderWidth: 1,
    borderColor: Colors.border,
    padding: 5,
  },
  segBtn: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
    gap: 4,
    paddingVertical: 12,
    borderRadius: 12,
  },
  segBtnOn: { backgroundColor: Colors.amber },
  segText: { fontFamily: "Inter_600SemiBold", fontSize: 12, color: Colors.textSecondary },
  segTextOn: { color: "#0B0500" },
  toggleList: { gap: 8 },
  toggleRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 12,
    padding: 16,
    borderRadius: 16,
    borderWidth: 1,
    borderColor: Colors.border,
    backgroundColor: "rgba(255,255,255,0.03)",
  },
  toggleRowOn: {
    borderColor: Colors.amber,
    backgroundColor: "rgba(255,122,24,0.10)",
  },
  toggleTitle: { fontFamily: "Inter_700Bold", fontSize: 15, color: Colors.text },
  toggleDesc: {
    fontFamily: "Inter_400Regular",
    fontSize: 12,
    color: Colors.textTertiary,
    marginTop: 3,
    lineHeight: 17,
  },
  chips: { flexDirection: "row", flexWrap: "wrap", gap: 10 },
  chip: {
    flexDirection: "row",
    alignItems: "center",
    paddingHorizontal: 16,
    paddingVertical: 10,
    borderRadius: 999,
    borderWidth: 1,
    borderColor: Colors.borderStrong,
    backgroundColor: "rgba(255,255,255,0.02)",
  },
  chipOn: { backgroundColor: Colors.amber, borderColor: Colors.amber },
  chipDangerOn: {
    backgroundColor: "rgba(239,68,68,0.15)",
    borderColor: "rgba(239,68,68,0.40)",
  },
  chipText: { fontFamily: "Inter_500Medium", fontSize: 14, color: Colors.textSecondary },
  chipTextOn: { color: "#0B0500", fontFamily: "Inter_600SemiBold" },
  chipDangerText: { color: "#FCA5A5" },
  center: { alignItems: "center", justifyContent: "center", paddingVertical: 24 },
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
  errorText: {
    fontFamily: "Inter_500Medium",
    fontSize: 14,
    color: Colors.danger,
    textAlign: "center",
  },
});
