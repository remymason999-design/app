import { Ionicons } from "@expo/vector-icons";
import * as Haptics from "expo-haptics";
import { router } from "expo-router";
import { useEffect, useMemo, useState } from "react";
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
import { ProviderLogo } from "@/components/ProviderLogo";
import { PlanSelector } from "@/components/services/PlanSelector";
import { Colors } from "@/constants/colors";
import { useAuth } from "@/context/AuthContext";
import { getFriendlyMessage } from "@/lib/api";
import { updatePreferences } from "@/lib/onboarding-api";
import { providerDisplayName } from "@/lib/providers";
import { analytics, EVENTS } from "@/lib/analytics";
import {
  PricingService,
  SubscriptionPlanSelection,
  SubscriptionPlansMap,
  defaultHighlightPlan,
  fetchPricingServices,
} from "@/lib/pricing-api";

const gbp = (n: number) => `£${n.toFixed(2)}`;

export default function OnboardingServices() {
  const { user, setUser } = useAuth();
  const insets = useSafeAreaInsets();

  const [plans, setPlans] = useState<SubscriptionPlansMap>(
    () => ((user?.subscription_plans as SubscriptionPlansMap) || {})
  );
  const [sheetService, setSheetService] = useState<PricingService | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const query = useQuery<PricingService[]>({
    queryKey: ["/pricing/services"],
    queryFn: fetchPricingServices,
  });
  const services = query.data ?? [];
  useEffect(() => {
    analytics.capture(EVENTS.ONBOARDING_STARTED, { source: "onboarding" }, { user });
  }, []);

  const selectedIds = useMemo(() => Object.keys(plans), [plans]);

  const openService = (service: PricingService) => {
    Haptics.selectionAsync();
    setSheetService(service);
  };

  const toggleOff = (id: string) => {
    Haptics.selectionAsync();
    setPlans((prev) => {
      const next = { ...prev };
      delete next[id];
      return next;
    });
  };

  const onConfirmPlan = (selection: SubscriptionPlanSelection) => {
    if (!sheetService) return;
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
    setPlans((prev) => ({ ...prev, [sheetService.id]: selection }));
    setSheetService(null);
  };

  const monthlyTotal = useMemo(
    () => Object.values(plans).reduce((sum, p) => sum + (p.effective_monthly_cost || 0), 0),
    [plans]
  );

  const onContinue = async () => {
    if (saving) return;
    setSaving(true);
    try {
      if (selectedIds.length > 0) {
        const updated = await updatePreferences({
          services: selectedIds,
          subscription_plans: plans,
        });
        setUser(updated);
        analytics.capture(EVENTS.ONBOARDING_STEP_COMPLETED, { step: "services", selected_count: selectedIds.length }, { user: updated });
      }
      router.push("/onboarding/genres");
    } catch (e) {
      Haptics.notificationAsync(Haptics.NotificationFeedbackType.Error);
      setError(getFriendlyMessage(e));
    } finally {
      setSaving(false);
    }
  };

  const currentSheetSelection = sheetService ? plans[sheetService.id] ?? null : null;

  return (
    <View style={styles.root}>
      <ScrollView
        contentContainerStyle={[
          styles.content,
          { paddingTop: insets.top + 20, paddingBottom: 160 },
        ]}
        keyboardShouldPersistTaps="handled"
      >
        <OnboardingProgress step={1} />
        <Text style={styles.eyebrow}>Step 1 of 4</Text>
        <Text style={styles.h1}>Where do you watch?</Text>
        <Text style={styles.sub}>
          Pick your services and confirm the exact plan you&apos;re on.
        </Text>

        {query.isLoading ? (
          <View style={styles.center}>
            <ActivityIndicator color={Colors.amber} />
          </View>
        ) : query.isError ? (
          <View style={styles.center}>
            <Text style={styles.errorText}>Couldn&apos;t load streaming services.</Text>
            <Pressable
              onPress={() => query.refetch()}
              style={styles.retryBtn}
              accessibilityRole="button"
              accessibilityLabel="Retry loading services"
            >
              <Text style={styles.retryText}>Retry</Text>
            </Pressable>
          </View>
        ) : services.length === 0 ? (
          <View style={styles.center}>
            <Text style={styles.errorText}>No streaming services available.</Text>
          </View>
        ) : (
          <View style={styles.grid}>
            {services.map((s) => {
              const sel = plans[s.id];
              const on = !!sel;
              const name = providerDisplayName(s.id, s.name);
              const dflt = defaultHighlightPlan(s.plans);
              return (
                <Pressable
                  key={s.id}
                  onPress={() => openService(s)}
                  onLongPress={() => {
                    if (on) toggleOff(s.id);
                  }}
                  style={[styles.serviceCard, on && styles.serviceCardOn]}
                  accessibilityRole="button"
                  accessibilityState={{ selected: on }}
                  accessibilityLabel={
                    on
                      ? `${name}, plan selected, effective ${gbp(
                          sel.effective_monthly_cost
                        )} per month. Tap to change, long press to remove.`
                      : `${name}, tap to choose a plan`
                  }
                >
                  <View style={styles.logoWrap}>
                    <ProviderLogo
                      sid={s.id}
                      name={s.name}
                      logoUrl={s.logo_path}
                      size={40}
                      radius={10}
                    />
                  </View>
                  <Text style={styles.serviceName}>{name}</Text>
                  <Text style={styles.servicePrice}>
                    {on
                      ? sel.effective_monthly_cost > 0
                        ? `${gbp(sel.effective_monthly_cost)}/mo`
                        : "£0/mo"
                      : dflt && dflt.monthly_price != null && dflt.monthly_price > 0
                        ? `from ${gbp(dflt.monthly_price)}/mo`
                        : "Choose plan"}
                  </Text>
                  {on ? (
                    <View style={styles.check}>
                      <Ionicons name="checkmark" size={14} color="#0B0500" />
                    </View>
                  ) : null}
                </Pressable>
              );
            })}
          </View>
        )}

        {selectedIds.length > 0 ? (
          <Text style={styles.hint}>
            Tap a selected service to change plan, or long-press to remove it.
          </Text>
        ) : null}

        {error ? <Text style={styles.errorText}>{error}</Text> : null}
      </ScrollView>

      <View style={[styles.bottomBar, { paddingBottom: insets.bottom + 16 }]}>
        <View>
          <Text style={styles.spendLabel}>You spend</Text>
          <Text style={styles.spendValue}>
            {gbp(monthlyTotal)}
            <Text style={styles.spendUnit}>/mo</Text>
          </Text>
        </View>
        <Pressable
          onPress={onContinue}
          disabled={saving}
          style={[styles.primaryBtn, saving && styles.btnDisabled]}
          accessibilityRole="button"
          accessibilityLabel={selectedIds.length === 0 ? "Skip" : "Continue"}
        >
          {saving ? (
            <ActivityIndicator color="#0B0500" />
          ) : (
            <Text style={styles.primaryBtnText}>
              {selectedIds.length === 0 ? "Skip" : "Continue"}
            </Text>
          )}
        </Pressable>
      </View>

      <PlanSelector
        visible={!!sheetService}
        service={sheetService}
        current={currentSheetSelection}
        onConfirm={onConfirmPlan}
        onClose={() => setSheetService(null)}
      />
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
  grid: { flexDirection: "row", flexWrap: "wrap", gap: 12 },
  serviceCard: {
    width: "47%",
    flexGrow: 1,
    borderWidth: 1,
    borderColor: Colors.border,
    backgroundColor: "rgba(255,255,255,0.03)",
    borderRadius: 18,
    padding: 16,
  },
  serviceCardOn: {
    borderColor: Colors.amber,
    backgroundColor: "rgba(255,122,24,0.10)",
  },
  logoWrap: { marginBottom: 12 },
  serviceName: { fontFamily: "Inter_700Bold", fontSize: 15, color: Colors.text },
  servicePrice: {
    fontFamily: "Inter_400Regular",
    fontSize: 12,
    color: Colors.textSecondary,
    marginTop: 4,
  },
  hint: {
    fontFamily: "Inter_400Regular",
    fontSize: 12,
    color: Colors.textTertiary,
    marginTop: 16,
    lineHeight: 17,
  },
  check: {
    position: "absolute",
    top: 12,
    right: 12,
    width: 24,
    height: 24,
    borderRadius: 12,
    backgroundColor: Colors.amber,
    alignItems: "center",
    justifyContent: "center",
  },
  bottomBar: {
    position: "absolute",
    left: 0,
    right: 0,
    bottom: 0,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingHorizontal: 24,
    paddingTop: 16,
    backgroundColor: Colors.velvet,
    borderTopWidth: 1,
    borderTopColor: Colors.border,
  },
  spendLabel: {
    fontFamily: "Inter_500Medium",
    fontSize: 11,
    letterSpacing: 1,
    textTransform: "uppercase",
    color: Colors.textTertiary,
  },
  spendValue: {
    fontFamily: "Inter_800ExtraBold",
    fontSize: 22,
    color: Colors.text,
    marginTop: 2,
  },
  spendUnit: { fontFamily: "Inter_500Medium", fontSize: 13, color: Colors.textTertiary },
  primaryBtn: {
    backgroundColor: Colors.amber,
    paddingHorizontal: 28,
    paddingVertical: 15,
    borderRadius: 16,
    minWidth: 120,
    alignItems: "center",
    justifyContent: "center",
  },
  primaryBtnText: { fontFamily: "Inter_700Bold", fontSize: 16, color: "#0B0500" },
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
