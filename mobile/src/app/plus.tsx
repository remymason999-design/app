import { Ionicons } from "@expo/vector-icons";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Stack, router, useLocalSearchParams } from "expo-router";
import { useEffect, useMemo, useState } from "react";
import {
  ActivityIndicator,
  Alert,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { Colors } from "@/constants/colors";
import { getFriendlyMessage } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import {
  PLUS_BENEFITS,
  PLUS_DEFAULT_CONFIG,
  PlusConfig,
  PlusInterest,
  addPlusInterest,
  fetchPlusConfig,
  fetchPlusInterest,
  removePlusInterest,
  sanitizePlusSource,
  trackPlusEvent,
} from "@/lib/plus-api";
import { plusInterestView, reconcilePlusInterest } from "@/lib/plus-state";

const CONFIRMATION = "You're on the list. We'll let you know when WatchSmart+ is ready.";

export default function PlusPreview() {
  const { user } = useAuth();
  const insets = useSafeAreaInsets();
  const params = useLocalSearchParams<{ source?: string | string[] }>();
  const sourceParam = Array.isArray(params.source) ? params.source[0] : params.source;
  const source = useMemo(
    () => sanitizePlusSource(sourceParam || "profile"),
    [sourceParam]
  );
  const qc = useQueryClient();
  const [busy, setBusy] = useState(false);

  const configQ = useQuery<PlusConfig>({
    queryKey: ["/monetization/config"],
    queryFn: fetchPlusConfig,
    staleTime: 5 * 60_000,
  });
  const interestQ = useQuery<PlusInterest>({
    queryKey: ["/monetization/plus/interest", user?.user_id],
    queryFn: fetchPlusInterest,
    enabled: !!user?.user_id,
    staleTime: 60_000,
  });
  const config = configQ.data?.flags ? configQ.data : PLUS_DEFAULT_CONFIG;
  const interestEnabled = interestQ.data?.enabled ?? config.flags.plus_interest_enabled;
  const interestView = plusInterestView({
    loading: interestQ.isLoading,
    error: interestQ.isError,
    interest: interestQ.data,
    enabled: interestEnabled,
  });

  useEffect(() => {
    trackPlusEvent("plus_preview_viewed", source);
    // Route entry is one visit; query retries do not run this again.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [source]);

  const notify = async () => {
    if (busy || interestQ.isLoading || !interestEnabled) return;
    setBusy(true);
    try {
      const result = await addPlusInterest(source);
      qc.setQueryData(
        ["/monetization/plus/interest", user?.user_id],
        (current: PlusInterest | undefined) => reconcilePlusInterest(current, true)
      );
      if (result.changed) {
        // No notification permission or payment flow is involved.
      }
    } catch (error) {
      // Keep the authoritative server state untouched on failure.
      Alert.alert("Couldn't save your interest", getFriendlyMessage(error));
    } finally {
      setBusy(false);
    }
  };

  const remove = async () => {
    if (busy) return;
    setBusy(true);
    try {
      await removePlusInterest();
      qc.setQueryData(
        ["/monetization/plus/interest", user?.user_id],
        (current: PlusInterest | undefined) => reconcilePlusInterest(current, false)
      );
    } catch (error) {
      Alert.alert("Couldn't update your interest", getFriendlyMessage(error));
    } finally {
      setBusy(false);
    }
  };

  if (!configQ.isLoading && config.flags.plus_visible === false) {
    return (
      <View style={styles.center}>
        <Stack.Screen options={{ headerShown: false }} />
        <Ionicons name="alert-circle-outline" size={44} color={Colors.textSecondary} />
        <Text style={styles.errorTitle}>WatchSmart+ is unavailable</Text>
        <Text style={styles.muted}>Please try again later.</Text>
        <Pressable onPress={() => configQ.refetch()} style={styles.primaryBtn}>
          <Text style={styles.primaryBtnText}>Try again</Text>
        </Pressable>
      </View>
    );
  }

  return (
    <View style={styles.root}>
      <Stack.Screen options={{ headerShown: false }} />
      <ScrollView
        showsVerticalScrollIndicator={false}
        contentContainerStyle={{ paddingTop: insets.top + 12, paddingBottom: insets.bottom + 36 }}
      >
        <View style={styles.topBar}>
          <Pressable
            onPress={() => router.back()}
            style={styles.iconBtn}
            accessibilityRole="button"
            accessibilityLabel="Go back"
            testID="plus-back"
          >
            <Ionicons name="arrow-back" size={22} color={Colors.text} />
          </Pressable>
          <Text style={styles.previewLabel}>PREVIEW</Text>
          <View style={styles.iconSpacer} />
        </View>

        {configQ.isError ? (
          <View style={styles.warning}>
            <Ionicons name="warning-outline" size={18} color={Colors.amber} />
            <Text style={styles.warningText}>Some preview settings couldn&apos;t be refreshed.</Text>
            <Pressable onPress={() => configQ.refetch()} accessibilityRole="button">
              <Text style={styles.retryText}>Retry</Text>
            </Pressable>
          </View>
        ) : null}

        <View style={styles.hero} testID="plus-hero">
          <View style={styles.heroIcon}>
            <Ionicons name="sparkles" size={23} color={Colors.obsidian} />
          </View>
          <Text style={styles.heroTitle}>WatchSmart+</Text>
          <Text style={styles.status}>COMING SOON</Text>
          <Text style={styles.intro}>We&apos;re building even more ways to make streaming smarter.</Text>
        </View>

        <View style={styles.benefits}>
          {PLUS_BENEFITS.map(([heading, copy]) => (
            <View key={heading} style={styles.benefit}>
              <View style={styles.benefitIcon}>
                <Ionicons name="chevron-forward" size={16} color={Colors.amber} />
              </View>
              <View style={styles.benefitCopy}>
                <Text style={styles.benefitHeading}>{heading}</Text>
                <Text style={styles.benefitText}>{copy}</Text>
              </View>
            </View>
          ))}
        </View>

        <View style={styles.interestCard} testID="plus-interest">
          <Text style={styles.interestTitle}>Interested in WatchSmart+?</Text>
          {interestView === "error" ? (
            <View style={styles.inlineError}>
              <Text style={styles.muted}>We couldn&apos;t check your current interest status.</Text>
              <Pressable onPress={() => interestQ.refetch()} accessibilityRole="button">
                <Text style={styles.retryText}>Retry</Text>
              </Pressable>
            </View>
          ) : interestView === "interested" ? (
            <>
              <View style={styles.confirmation}>
                <Ionicons name="checkmark-circle" size={18} color={Colors.success} />
                <Text style={styles.confirmationText}>{CONFIRMATION}</Text>
              </View>
              <Pressable onPress={remove} disabled={busy} accessibilityRole="button" testID="plus-interest-remove">
                <Text style={[styles.removeText, busy && styles.dim]}>{busy ? "Updating…" : "Remove me from the list"}</Text>
              </Pressable>
            </>
          ) : interestView === "disabled" ? (
            <Text style={styles.muted}>Interest registration is not available right now.</Text>
          ) : (
            <>
              <Text style={styles.muted}>We&apos;ll only use this to let you know when the preview becomes available.</Text>
              <Pressable onPress={notify} disabled={busy || interestQ.isLoading} style={styles.notifyBtn} testID="plus-interest-btn">
                {busy ? <ActivityIndicator color={Colors.obsidian} /> : <Ionicons name="notifications-outline" size={18} color={Colors.obsidian} />}
                <Text style={styles.notifyText}>{busy ? "Saving…" : "Notify me when it launches"}</Text>
              </Pressable>
            </>
          )}
        </View>
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: Colors.obsidian },
  center: { flex: 1, backgroundColor: Colors.obsidian, alignItems: "center", justifyContent: "center", padding: 28, gap: 12 },
  errorTitle: { fontFamily: "Inter_700Bold", fontSize: 22, color: Colors.text, marginTop: 4 },
  muted: { fontFamily: "Inter_400Regular", fontSize: 13, lineHeight: 19, color: Colors.textSecondary },
  primaryBtn: { backgroundColor: Colors.amber, borderRadius: 14, paddingHorizontal: 22, paddingVertical: 12, marginTop: 8 },
  primaryBtnText: { fontFamily: "Inter_700Bold", color: Colors.obsidian, fontSize: 14 },
  topBar: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingHorizontal: 20 },
  iconBtn: { width: 42, height: 42, borderRadius: 21, backgroundColor: Colors.surface, alignItems: "center", justifyContent: "center" },
  iconSpacer: { width: 42 },
  previewLabel: { fontFamily: "Inter_600SemiBold", fontSize: 11, letterSpacing: 1.8, color: Colors.textTertiary },
  warning: { flexDirection: "row", alignItems: "center", gap: 8, marginHorizontal: 20, marginTop: 16, padding: 13, borderRadius: 14, borderWidth: 1, borderColor: "rgba(255,122,24,0.25)", backgroundColor: "rgba(255,122,24,0.06)" },
  warningText: { flex: 1, fontFamily: "Inter_400Regular", fontSize: 12, color: Colors.textSecondary },
  retryText: { fontFamily: "Inter_600SemiBold", fontSize: 13, color: Colors.amber },
  hero: { marginHorizontal: 20, marginTop: 24, padding: 22, borderRadius: 24, borderWidth: 1, borderColor: "rgba(255,122,24,0.35)", backgroundColor: "rgba(255,122,24,0.10)" },
  heroIcon: { width: 46, height: 46, borderRadius: 15, backgroundColor: Colors.amber, alignItems: "center", justifyContent: "center", marginBottom: 16 },
  heroTitle: { fontFamily: "Inter_800ExtraBold", fontSize: 30, color: Colors.text },
  status: { fontFamily: "Inter_700Bold", fontSize: 11, letterSpacing: 1.6, color: Colors.amber, marginTop: 8 },
  intro: { fontFamily: "Inter_400Regular", fontSize: 15, lineHeight: 23, color: Colors.textSecondary, marginTop: 20 },
  benefits: { gap: 9, marginHorizontal: 20, marginTop: 24 },
  benefit: { flexDirection: "row", gap: 11, padding: 14, borderRadius: 16, borderWidth: 1, borderColor: Colors.border, backgroundColor: "rgba(255,255,255,0.03)" },
  benefitIcon: { width: 30, height: 30, borderRadius: 11, backgroundColor: "rgba(255,122,24,0.10)", alignItems: "center", justifyContent: "center" },
  benefitCopy: { flex: 1 },
  benefitHeading: { fontFamily: "Inter_700Bold", fontSize: 13, letterSpacing: 0.8, color: Colors.text },
  benefitText: { fontFamily: "Inter_400Regular", fontSize: 13, lineHeight: 19, color: Colors.textSecondary, marginTop: 4 },
  interestCard: { marginHorizontal: 20, marginTop: 28, padding: 18, borderRadius: 20, borderWidth: 1, borderColor: Colors.border, backgroundColor: Colors.surface },
  interestTitle: { fontFamily: "Inter_700Bold", fontSize: 17, color: Colors.text, marginBottom: 8 },
  inlineError: { gap: 10 },
  confirmation: { flexDirection: "row", alignItems: "flex-start", gap: 8, marginTop: 8, marginBottom: 18 },
  confirmationText: { flex: 1, fontFamily: "Inter_400Regular", fontSize: 13, lineHeight: 19, color: "#86EFAC" },
  removeText: { fontFamily: "Inter_500Medium", fontSize: 13, color: Colors.textSecondary, textDecorationLine: "underline" },
  notifyBtn: { marginTop: 18, minHeight: 50, borderRadius: 15, backgroundColor: Colors.amber, flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8 },
  notifyText: { fontFamily: "Inter_700Bold", fontSize: 14, color: Colors.obsidian },
  dim: { opacity: 0.45 },
});