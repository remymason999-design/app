/**
 * PlanSelector — the shared subscription-plan chooser used by both the
 * onboarding "Where do you watch?" step and Profile → Streaming services.
 *
 * Rendered inside a bottom-sheet-style modal. For the given service it shows:
 *   - the service's primary plans (active, non-add-on) as selectable rows,
 *     each with name, £monthly price, Ads/Ad-free, quality and streams where
 *     known;
 *   - a monthly / annual toggle where an annual price exists (shows the real
 *     annual payment);
 *   - an "Included with another subscription" toggle (effective cost £0
 *     unless a custom price is entered);
 *   - "Enter my own price" numeric (GBP) input for legacy / bundle / promo /
 *     student pricing;
 *   - optional add-on plans (e.g. Boost) listed separately.
 *
 * The most expensive plan is never preselected — the cheapest paid plan is
 * highlighted by default but the user must tap Confirm to commit.
 *
 * Free services show "Free"; BBC iPlayer (licence_required) shows "TV Licence
 * required" and contributes £0.
 */
import { Ionicons } from "@expo/vector-icons";
import { useMemo, useState } from "react";
import {
  KeyboardAvoidingView,
  Modal,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Switch,
  Text,
  TextInput,
  View,
} from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { ProviderLogo } from "@/components/ProviderLogo";
import { Colors } from "@/constants/colors";
import { providerDisplayName } from "@/lib/providers";
import {
  BillingCycle,
  PricingPlan,
  PricingService,
  SubscriptionPlanSelection,
  addonPlans,
  defaultHighlightPlan,
  effectiveMonthlyCost,
  isFreePlan,
  isLicencePlan,
  primaryPlans,
} from "@/lib/pricing-api";

const gbp = (n: number, decimals = 2) => `£${n.toFixed(decimals)}`;

interface Props {
  visible: boolean;
  service: PricingService | null;
  /** Existing selection to pre-fill (when editing an already-chosen plan). */
  current?: SubscriptionPlanSelection | null;
  onConfirm: (selection: SubscriptionPlanSelection) => void;
  onClose: () => void;
}

function planSummary(p: PricingPlan): string {
  const bits: string[] = [];
  if (p.has_ads === true) bits.push("Ads");
  else if (p.has_ads === false) bits.push("Ad-free");
  if (p.video_quality) bits.push(p.video_quality);
  if (p.simultaneous_streams && p.simultaneous_streams > 0) {
    bits.push(`${p.simultaneous_streams} stream${p.simultaneous_streams === 1 ? "" : "s"}`);
  }
  return bits.join(" · ");
}

function planPriceLabel(p: PricingPlan, cycle: BillingCycle): string {
  if (isFreePlan(p)) return "Free";
  if (isLicencePlan(p)) return "TV Licence required";
  if (cycle === "annual" && p.annual_price != null) {
    return `${gbp(p.annual_price)}/yr`;
  }
  return p.monthly_price != null ? `${gbp(p.monthly_price)}/mo` : "—";
}

export function PlanSelector({ visible, service, current, onConfirm, onClose }: Props) {
  const insets = useSafeAreaInsets();

  const plans = useMemo(() => (service ? primaryPlans(service.plans) : []), [service]);
  const addons = useMemo(() => (service ? addonPlans(service.plans) : []), [service]);

  // Resolve the initial selection: prefer the existing one, else default
  // highlight (cheapest paid plan) — but require explicit confirm.
  const initialPlanId = useMemo(() => {
    if (current?.plan_id) return current.plan_id;
    const d = defaultHighlightPlan(service?.plans ?? []);
    return d?.id ?? null;
  }, [current, service]);

  const [selectedPlanId, setSelectedPlanId] = useState<string | null>(initialPlanId);
  const [billingCycle, setBillingCycle] = useState<BillingCycle>(
    current?.billing_cycle ?? "monthly"
  );
  const [includedWithOther, setIncludedWithOther] = useState<boolean>(
    current?.included_with_other_provider ?? false
  );
  const [customPriceText, setCustomPriceText] = useState<string>(
    current?.custom_price != null ? String(current.custom_price) : ""
  );

  // Re-seed local state whenever we open for a different service / selection.
  const seedKey = `${service?.id ?? ""}:${current?.plan_id ?? ""}`;
  const [lastSeed, setLastSeed] = useState<string>(seedKey);
  if (visible && seedKey !== lastSeed) {
    setLastSeed(seedKey);
    setSelectedPlanId(initialPlanId);
    setBillingCycle(current?.billing_cycle ?? "monthly");
    setIncludedWithOther(current?.included_with_other_provider ?? false);
    setCustomPriceText(current?.custom_price != null ? String(current.custom_price) : "");
  }

  const selectedPlan = plans.find((p) => p.id === selectedPlanId) ?? null;
  const customPrice = customPriceText.trim() === "" ? null : Number(customPriceText);
  const hasCustom = customPrice != null && !Number.isNaN(customPrice);

  const anyAnnual = plans.some((p) => p.annual_price != null);
  const selectedHasAnnual = selectedPlan?.annual_price != null;

  const cost = effectiveMonthlyCost(selectedPlan, {
    billingCycle,
    includedWithOther,
    customPrice: hasCustom ? customPrice : null,
  });

  const name = service ? providerDisplayName(service.id, service.name) : "";

  const confirm = () => {
    onConfirm({
      plan_id: selectedPlanId,
      billing_cycle: billingCycle,
      effective_monthly_cost: Number(cost.toFixed(2)),
      included_with_other_provider: includedWithOther,
      custom_price: hasCustom ? Number(customPrice!.toFixed(2)) : null,
    });
  };

  return (
    <Modal
      visible={visible}
      transparent
      animationType="slide"
      onRequestClose={onClose}
      statusBarTranslucent
    >
      <Pressable style={styles.backdrop} onPress={onClose} accessibilityLabel="Dismiss" />
      <KeyboardAvoidingView
        behavior={Platform.OS === "ios" ? "padding" : undefined}
        style={styles.sheetWrap}
        pointerEvents="box-none"
      >
        <View style={[styles.sheet, { paddingBottom: insets.bottom + 16 }]}>
          <View style={styles.handle} />
          <View style={styles.headerRow}>
            {service ? (
              <ProviderLogo
                sid={service.id}
                name={service.name}
                logoUrl={service.logo_path}
                size={40}
                radius={10}
              />
            ) : null}
            <View style={{ flex: 1 }}>
              <Text style={styles.eyebrow}>Choose your plan</Text>
              <Text style={styles.title}>{name}</Text>
            </View>
            <Pressable
              onPress={onClose}
              hitSlop={12}
              accessibilityRole="button"
              accessibilityLabel="Close plan selector"
            >
              <Ionicons name="close" size={24} color={Colors.textSecondary} />
            </Pressable>
          </View>

          <ScrollView
            style={{ maxHeight: 460 }}
            contentContainerStyle={{ paddingBottom: 8 }}
            keyboardShouldPersistTaps="handled"
          >
            {/* Monthly / annual toggle where an annual price exists */}
            {anyAnnual ? (
              <View style={styles.cycleRow}>
                {(["monthly", "annual"] as BillingCycle[]).map((c) => {
                  const active = billingCycle === c;
                  return (
                    <Pressable
                      key={c}
                      onPress={() => setBillingCycle(c)}
                      style={[styles.cycleBtn, active && styles.cycleBtnActive]}
                      accessibilityRole="button"
                      accessibilityState={{ selected: active }}
                      accessibilityLabel={c === "monthly" ? "Bill monthly" : "Bill annually"}
                    >
                      <Text style={[styles.cycleText, active && styles.cycleTextActive]}>
                        {c === "monthly" ? "Monthly" : "Annual"}
                      </Text>
                    </Pressable>
                  );
                })}
              </View>
            ) : null}

            {/* Plans */}
            {plans.map((p) => {
              const on = selectedPlanId === p.id;
              const summary = planSummary(p);
              return (
                <Pressable
                  key={p.id}
                  onPress={() => setSelectedPlanId(p.id)}
                  style={[styles.planRow, on && styles.planRowOn]}
                  accessibilityRole="radio"
                  accessibilityState={{ selected: on }}
                  accessibilityLabel={`${p.name}, ${planPriceLabel(p, billingCycle)}${
                    summary ? `, ${summary}` : ""
                  }`}
                >
                  <View style={[styles.radio, on && styles.radioOn]}>
                    {on ? <View style={styles.radioDot} /> : null}
                  </View>
                  <View style={{ flex: 1 }}>
                    <View style={styles.planNameRow}>
                      <Text style={styles.planName}>{p.name}</Text>
                      {p.is_promo ? (
                        <View style={styles.promoTag}>
                          <Text style={styles.promoTagText}>PROMO</Text>
                        </View>
                      ) : null}
                    </View>
                    {summary ? <Text style={styles.planSummary}>{summary}</Text> : null}
                  </View>
                  <Text style={styles.planPrice}>{planPriceLabel(p, billingCycle)}</Text>
                </Pressable>
              );
            })}

            {selectedCycleHint(selectedPlan, billingCycle, selectedHasAnnual)}

            {/* Add-ons (optional) */}
            {addons.length > 0 ? (
              <View style={styles.addonBlock}>
                <Text style={styles.addonLabel}>Optional add-ons</Text>
                {addons.map((a) => (
                  <View key={a.id} style={styles.addonRow}>
                    <Text style={styles.addonName}>{a.name}</Text>
                    <Text style={styles.addonPrice}>
                      {a.monthly_price != null ? `+${gbp(a.monthly_price)}/mo` : ""}
                    </Text>
                  </View>
                ))}
              </View>
            ) : null}

            {/* Included with another subscription */}
            <View style={styles.toggleRow}>
              <View style={{ flex: 1 }}>
                <Text style={styles.toggleTitle}>Included with another subscription</Text>
                <Text style={styles.toggleSub}>
                  e.g. bundled with your mobile or broadband. Counts as £0 unless you enter a
                  price.
                </Text>
              </View>
              <Switch
                value={includedWithOther}
                onValueChange={setIncludedWithOther}
                trackColor={{ false: Colors.surfaceLight, true: Colors.amber }}
                thumbColor="#FFFFFF"
                accessibilityLabel="Included with another subscription"
              />
            </View>

            {/* Custom price */}
            <View style={styles.customBlock}>
              <Text style={styles.toggleTitle}>Enter my own price</Text>
              <Text style={styles.toggleSub}>
                For legacy, bundle, promo or student pricing. Overrides the plan price.
              </Text>
              <View style={styles.customInputRow}>
                <Text style={styles.customCurrency}>£</Text>
                <TextInput
                  value={customPriceText}
                  onChangeText={(t) => setCustomPriceText(t.replace(/[^0-9.]/g, ""))}
                  keyboardType="decimal-pad"
                  placeholder="0.00"
                  placeholderTextColor={Colors.textTertiary}
                  style={styles.customInput}
                  accessibilityLabel="Custom monthly price in pounds"
                />
                <Text style={styles.customUnit}>/mo</Text>
              </View>
            </View>
          </ScrollView>

          {/* Effective cost + confirm */}
          <View style={styles.footer}>
            <View>
              <Text style={styles.footerLabel}>Effective cost</Text>
              <Text style={styles.footerValue}>
                {gbp(cost)}
                <Text style={styles.footerUnit}>/mo</Text>
              </Text>
            </View>
            <Pressable
              onPress={confirm}
              style={styles.confirmBtn}
              accessibilityRole="button"
              accessibilityLabel="Confirm plan"
            >
              <Text style={styles.confirmText}>Confirm plan</Text>
            </Pressable>
          </View>
        </View>
      </KeyboardAvoidingView>
    </Modal>
  );
}

function selectedCycleHint(
  plan: PricingPlan | null,
  cycle: BillingCycle,
  hasAnnual: boolean
) {
  if (!plan || cycle !== "annual" || !hasAnnual || plan.annual_price == null) return null;
  return (
    <Text style={styles.cycleHint}>
      You&apos;ll pay {gbp(plan.annual_price)} today for 12 months (
      {gbp(plan.annual_price / 12)}/mo).
    </Text>
  );
}

const styles = StyleSheet.create({
  backdrop: { ...StyleSheet.absoluteFillObject, backgroundColor: "rgba(0,0,0,0.6)" },
  sheetWrap: { flex: 1, justifyContent: "flex-end" },
  sheet: {
    backgroundColor: Colors.velvet,
    borderTopLeftRadius: 28,
    borderTopRightRadius: 28,
    borderTopWidth: 1,
    borderColor: Colors.border,
    paddingHorizontal: 20,
    paddingTop: 10,
  },
  handle: {
    alignSelf: "center",
    width: 40,
    height: 4,
    borderRadius: 2,
    backgroundColor: Colors.borderStrong,
    marginBottom: 14,
  },
  headerRow: { flexDirection: "row", alignItems: "flex-start", gap: 12, marginBottom: 12 },
  eyebrow: {
    fontFamily: "Inter_600SemiBold",
    fontSize: 10,
    letterSpacing: 1.5,
    textTransform: "uppercase",
    color: Colors.amber,
  },
  title: { fontFamily: "Inter_800ExtraBold", fontSize: 22, color: Colors.text, marginTop: 4 },
  cycleRow: {
    flexDirection: "row",
    gap: 6,
    backgroundColor: "rgba(255,255,255,0.03)",
    borderRadius: 14,
    borderWidth: 1,
    borderColor: Colors.border,
    padding: 5,
    marginBottom: 14,
  },
  cycleBtn: { flex: 1, alignItems: "center", paddingVertical: 9, borderRadius: 10 },
  cycleBtnActive: { backgroundColor: Colors.amber },
  cycleText: { fontFamily: "Inter_600SemiBold", fontSize: 13, color: Colors.textSecondary },
  cycleTextActive: { color: "#0B0500" },
  planRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 12,
    padding: 14,
    borderRadius: 14,
    borderWidth: 1,
    borderColor: Colors.border,
    backgroundColor: "rgba(255,255,255,0.03)",
    marginBottom: 8,
  },
  planRowOn: { borderColor: Colors.amber, backgroundColor: "rgba(255,122,24,0.10)" },
  radio: {
    width: 22,
    height: 22,
    borderRadius: 11,
    borderWidth: 2,
    borderColor: Colors.borderStrong,
    alignItems: "center",
    justifyContent: "center",
  },
  radioOn: { borderColor: Colors.amber },
  radioDot: { width: 10, height: 10, borderRadius: 5, backgroundColor: Colors.amber },
  planNameRow: { flexDirection: "row", alignItems: "center", gap: 8 },
  planName: { fontFamily: "Inter_700Bold", fontSize: 15, color: Colors.text },
  promoTag: {
    backgroundColor: "rgba(255,122,24,0.18)",
    borderRadius: 6,
    paddingHorizontal: 6,
    paddingVertical: 2,
  },
  promoTagText: {
    fontFamily: "Inter_700Bold",
    fontSize: 9,
    letterSpacing: 1,
    color: Colors.amber,
  },
  planSummary: {
    fontFamily: "Inter_400Regular",
    fontSize: 12,
    color: Colors.textTertiary,
    marginTop: 3,
  },
  planPrice: { fontFamily: "Inter_700Bold", fontSize: 14, color: Colors.text },
  cycleHint: {
    fontFamily: "Inter_400Regular",
    fontSize: 12,
    color: Colors.textSecondary,
    marginBottom: 8,
    lineHeight: 17,
  },
  addonBlock: {
    borderTopWidth: 1,
    borderTopColor: Colors.border,
    paddingTop: 12,
    marginTop: 4,
    marginBottom: 8,
  },
  addonLabel: {
    fontFamily: "Inter_600SemiBold",
    fontSize: 11,
    letterSpacing: 1,
    textTransform: "uppercase",
    color: Colors.textTertiary,
    marginBottom: 8,
  },
  addonRow: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingVertical: 6,
  },
  addonName: { fontFamily: "Inter_500Medium", fontSize: 14, color: Colors.textSecondary },
  addonPrice: { fontFamily: "Inter_600SemiBold", fontSize: 13, color: Colors.textSecondary },
  toggleRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 12,
    paddingVertical: 12,
    borderTopWidth: 1,
    borderTopColor: Colors.border,
    marginTop: 4,
  },
  toggleTitle: { fontFamily: "Inter_600SemiBold", fontSize: 14, color: Colors.text },
  toggleSub: {
    fontFamily: "Inter_400Regular",
    fontSize: 12,
    color: Colors.textTertiary,
    marginTop: 3,
    lineHeight: 17,
  },
  customBlock: { paddingVertical: 12, borderTopWidth: 1, borderTopColor: Colors.border },
  customInputRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
    marginTop: 10,
    borderWidth: 1,
    borderColor: Colors.border,
    borderRadius: 12,
    paddingHorizontal: 14,
    backgroundColor: "rgba(255,255,255,0.03)",
  },
  customCurrency: { fontFamily: "Inter_700Bold", fontSize: 16, color: Colors.text },
  customInput: {
    flex: 1,
    fontFamily: "Inter_600SemiBold",
    fontSize: 16,
    color: Colors.text,
    paddingVertical: 12,
  },
  customUnit: { fontFamily: "Inter_500Medium", fontSize: 13, color: Colors.textTertiary },
  footer: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingTop: 14,
    borderTopWidth: 1,
    borderTopColor: Colors.border,
    marginTop: 4,
  },
  footerLabel: {
    fontFamily: "Inter_500Medium",
    fontSize: 11,
    letterSpacing: 1,
    textTransform: "uppercase",
    color: Colors.textTertiary,
  },
  footerValue: {
    fontFamily: "Inter_800ExtraBold",
    fontSize: 22,
    color: Colors.text,
    marginTop: 2,
  },
  footerUnit: { fontFamily: "Inter_500Medium", fontSize: 13, color: Colors.textTertiary },
  confirmBtn: {
    backgroundColor: Colors.amber,
    paddingHorizontal: 28,
    paddingVertical: 15,
    borderRadius: 16,
    minWidth: 140,
    alignItems: "center",
    justifyContent: "center",
  },
  confirmText: { fontFamily: "Inter_700Bold", fontSize: 16, color: "#0B0500" },
});
