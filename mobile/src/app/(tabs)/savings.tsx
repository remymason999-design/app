import { Ionicons } from "@expo/vector-icons";
import { useQuery } from "@tanstack/react-query";
import { Image } from "expo-image";
import { router } from "expo-router";
import { LayoutChangeEvent, NativeScrollEvent, NativeSyntheticEvent, Pressable, RefreshControl, StyleSheet, Text, View } from "react-native";
import { useCallback, useEffect, useRef } from "react";

import { ListEmpty, ListError, ListLoading } from "@/components/lists/ListStates";
import { ScreenContainer } from "@/components/layout/ScreenContainer";
import { ProviderLogo } from "@/components/ProviderLogo";
import { Colors } from "@/constants/colors";
import { getFriendlyMessage } from "@/lib/api";
import {
  fetchSavings,
  fetchSubscriptionsInsights,
  fetchWatchlistValue,
  SavingsData,
  SubscriptionsInsights,
  WatchlistValue,
} from "@/lib/social-api";
import { analytics, EVENTS } from "@/lib/analytics";

const formatMoney = (amount: number, currency: string = "£", decimals = 2) => `${currency}${amount.toFixed(decimals)}`;
const gbp = (n: number, decimals = 2) => formatMoney(n, "£", decimals);

export default function SavingsScreen() {
  useEffect(() => {
    analytics.capture(EVENTS.SAVINGS_SCREEN_VIEWED, {});
  }, []);
  const savingsQ = useQuery<SavingsData>({
    queryKey: ["/savings"],
    queryFn: fetchSavings,
  });
  const valueQ = useQuery<WatchlistValue>({
    queryKey: ["/watchlist/value"],
    queryFn: fetchWatchlistValue,
    // Optional supplementary data — a failure here shouldn't block the page.
    retry: 0,
  });
  const insightsQ = useQuery<SubscriptionsInsights>({
    queryKey: ["/insights/subscriptions"],
    queryFn: fetchSubscriptionsInsights,
    retry: 0,
  });
  const suggestionLayouts = useRef(new Map<number, { y: number; height: number }>());
  const viewedSuggestions = useRef(new Set<number>());
  const scrollY = useRef(0);
  const viewportHeight = useRef(0);
  const checkSuggestionVisibility = useCallback(() => {
    suggestionLayouts.current.forEach((layout, index) => {
      if (viewedSuggestions.current.has(index) || layout.height <= 0) return;
      const overlap = Math.max(0, Math.min(layout.y + layout.height, scrollY.current + viewportHeight.current) - Math.max(layout.y, scrollY.current));
      if (overlap / layout.height < 0.5) return;
      viewedSuggestions.current.add(index);
      const suggestion = savingsQ.data?.suggestions[index];
      analytics.capture(EVENTS.SAVINGS_RECOMMENDATION_VIEWED, {
        position: index,
        estimated_monthly_saving: suggestion?.monthly_savings,
      }, { dedupeKey: `savings-suggestion:${index}` });
    });
  }, [savingsQ.data?.suggestions]);
  const onScroll = useCallback((event: NativeSyntheticEvent<NativeScrollEvent>) => {
    scrollY.current = event.nativeEvent.contentOffset.y;
    viewportHeight.current = event.nativeEvent.layoutMeasurement.height;
    checkSuggestionVisibility();
  }, [checkSuggestionVisibility]);

  const onRefresh = () => {
    savingsQ.refetch();
    valueQ.refetch();
    insightsQ.refetch();
  };

  if (savingsQ.isLoading) {
    return (
      <ScreenContainer>
        <ListLoading />
      </ScreenContainer>
    );
  }

  if (savingsQ.isError || !savingsQ.data) {
    return (
      <ScreenContainer>
        <ListError
          message={getFriendlyMessage(savingsQ.error)}
          onRetry={savingsQ.refetch}
          testID="savings-error"
        />
      </ScreenContainer>
    );
  }

  const data = savingsQ.data;
  const totalSavings = data.suggestions.reduce((s, x) => s + (x.monthly_savings || 0), 0);
  const insights = insightsQ.data;
  const potentialSavings = totalSavings;
  const value = valueQ.data;
  const valueRows = (value?.services || []).filter((s) => s.titles_count > 0).slice(0, 5);

  const needsPlanCount = data.usage.filter((u) => u.needs_plan).length;

  const isEmpty = data.subscription_count === 0;

  return (
    <ScreenContainer
      scroll
      refreshControl={
        <RefreshControl
          refreshing={savingsQ.isRefetching || valueQ.isRefetching}
          onRefresh={onRefresh}
          tintColor={Colors.amber}
        />
      }
      onScroll={onScroll}
      onLayout={(event) => {
        viewportHeight.current = event.nativeEvent.layout.height;
        checkSuggestionVisibility();
      }}
      scrollEventThrottle={100}
    >
      <Text style={styles.kicker}>Your subscriptions</Text>
      <Text style={styles.h1}>Spend less.{"\n"}Watch more.</Text>

      {isEmpty ? (
        <ListEmpty
          icon="pricetags-outline"
          title="No subscriptions yet"
          body="Add the services you pay for in your profile to see spend and savings."
        />
      ) : (
        <>
          {/* Summary */}
          <View style={styles.summary} testID="savings-summary">
            <View style={styles.summaryRow}>
              <View>
                <Text style={styles.smallLabel}>Monthly</Text>
                <Text style={styles.big}>{gbp(data.total_monthly)}</Text>
                <Text style={styles.subtle}>{data.subscription_count} services</Text>
              </View>
              <View style={{ alignItems: "flex-end" }}>
                <Text style={styles.smallLabel}>Yearly</Text>
                <Text style={styles.big2}>{gbp(data.total_yearly, 0)}</Text>
              </View>
            </View>
            {potentialSavings > 0 && (
              <View style={styles.savingsBanner}>
                <View style={styles.savingsIcon}>
                  <Ionicons name="trending-down" size={20} color={Colors.amber} />
                </View>
                <View style={{ flex: 1 }}>
                  <Text style={styles.savingsTitle}>Potential saving: {gbp(potentialSavings)}/mo</Text>
                  <Text style={styles.subtle}>
                    Up to {gbp(potentialSavings * 12, 0)} a year from subscriptions worth reviewing.
                  </Text>
                </View>
              </View>
            )}
          </View>

          {insights?.services?.length ? (
            <>
              <Text style={styles.h2}>Recent subscription insights</Text>
              <Text style={[styles.subtle, { marginBottom: 12 }]}>
                {insights.month_label} · {insights.total_watched} title{insights.total_watched === 1 ? "" : "s"} watched
              </Text>
              {insights.services.map((service) => {
                const usage = data.usage.find((row) => row.service_id === service.service_id);
                const monthlyCost = usage?.monthly_cost ?? usage?.price_monthly ?? service.price_monthly;
                const costPerWatch = service.titles_watched > 0 ? monthlyCost / service.titles_watched : null;
                return (
                <View key={service.service_id} style={styles.card} testID={`insight-${service.service_id}`}>
                  <View style={styles.summaryRow}>
                    <ProviderLogo sid={service.service_id} name={service.name} size={34} radius={9} />
                    <View style={{ flex: 1 }}>
                      <Text style={styles.usageName}>{service.name}</Text>
                      <Text style={styles.subtle}>
                        {formatMoney(monthlyCost, insights.currency)}/mo
                        {costPerWatch != null
                          ? ` · ${formatMoney(costPerWatch, insights.currency)} per watch`
                          : ""}
                      </Text>
                    </View>
                    <View style={{ alignItems: "flex-end" }}>
                      <Text style={styles.usageCount}>{service.titles_watched}</Text>
                      <Text style={styles.tinyLabel}>watched</Text>
                    </View>
                  </View>
                  <View style={styles.insightReason}>
                    <Ionicons
                      name={service.tone === "low" ? "alert-circle-outline" : service.tone === "great" ? "sparkles-outline" : "information-circle-outline"}
                      size={16}
                      color={service.tone === "low" ? Colors.amber : Colors.textSecondary}
                    />
                    <View style={{ flex: 1 }}>
                      <Text style={styles.insightHeadline}>{service.headline}</Text>
                      <Text style={styles.cardBody}>{service.message}</Text>
                    </View>
                  </View>
                  {service.top_titles.length > 0 && (
                    <View style={styles.postersRow}>
                      {service.top_titles.map((title) => (
                        <View key={title.id} style={styles.miniPoster}>
                          {title.poster_url ? <Image source={{ uri: title.poster_url }} style={StyleSheet.absoluteFill} contentFit="cover" /> : null}
                        </View>
                      ))}
                    </View>
                  )}
                </View>
                );
              })}
            </>
          ) : null}

          {/* Smart suggestions */}
          <Text style={styles.h2}>Smart suggestions</Text>
          {data.suggestions.length === 0 ? (
            <View style={styles.card}>
              <View style={styles.rowStart}>
                <Ionicons name="sparkles" size={18} color={Colors.amber} />
                <Text style={styles.cardBody}>
                  Your stack looks balanced. Keep swiping and we’ll watch for ways to trim
                  spend.
                </Text>
              </View>
            </View>
          ) : (
            data.suggestions.map((s, i) => (
              <View
                key={i}
                style={styles.card}
                testID={`suggestion-${i}`}
                onLayout={(event: LayoutChangeEvent) => {
                  const { y, height } = event.nativeEvent.layout;
                  suggestionLayouts.current.set(i, { y, height });
                  checkSuggestionVisibility();
                }}
              >
                <View style={styles.rowStart}>
                  <View style={styles.sugIcon}>
                    <Ionicons
                      name={s.type === "cancel" ? "trending-down" : "sparkles"}
                      size={16}
                      color={Colors.amber}
                    />
                  </View>
                  <View style={{ flex: 1 }}>
                    <Text style={styles.sugHead}>
                      {s.type === "cancel"
                        ? `Review ${data.usage.find((u) => u.service_id === s.service_id)?.name || "this subscription"}`
                        : s.headline}
                    </Text>
                    <Text style={styles.cardBody}>{s.reason}</Text>
                    <Text style={styles.whyShown}>
                      Why shown: based on your recorded WatchSmart activity and current plan cost.
                    </Text>
                  </View>
                </View>
              </View>
            ))
          )}

          {/* Confirm-plan prompt when any subscribed service has no chosen plan */}
          {needsPlanCount > 0 && (
            <Pressable
              onPress={() => {
                analytics.capture(EVENTS.SAVINGS_ACTION_STARTED, { source: "savings" });
                router.push("/profile");
              }}
              style={({ pressed }) => [styles.planPrompt, pressed && { opacity: 0.85 }]}
              accessibilityRole="button"
              accessibilityLabel="Confirm your plan for accurate savings"
              testID="confirm-plan-prompt"
            >
              <Ionicons name="alert-circle-outline" size={18} color={Colors.amber} />
              <View style={{ flex: 1 }}>
                <Text style={styles.planPromptTitle}>Confirm your plan for accurate savings</Text>
                <Text style={styles.subtle}>
                  {needsPlanCount} service{needsPlanCount === 1 ? "" : "s"} still need a plan.
                  Tap to set them in your profile.
                </Text>
              </View>
              <Ionicons name="chevron-forward" size={16} color={Colors.textTertiary} />
            </Pressable>
          )}

          {/* Activity per service */}
          <Text style={styles.h2}>Activity per service</Text>
          {data.usage.map((u) => {
            const cost = u.monthly_cost != null ? u.monthly_cost : u.price_monthly;
            return (
              <View key={u.service_id} style={styles.usageRow} testID={`usage-${u.service_id}`}>
                <ProviderLogo sid={u.service_id} name={u.name} size={34} radius={9} />
                <View style={{ flex: 1 }}>
                  <Text style={styles.usageName}>{u.name}</Text>
                  {u.plan_name ? (
                    <Text style={styles.planTag}>{u.plan_name}</Text>
                  ) : u.needs_plan ? (
                    <Text style={styles.needsPlan}>Plan not set</Text>
                  ) : null}
                  <Text style={styles.subtle}>
                    {gbp(cost)}/mo · {u.available_unseen} new for you
                  </Text>
                </View>
                <View style={{ alignItems: "flex-end" }}>
                  <Text style={styles.usageCount}>{u.activity_count}</Text>
                  <Text style={styles.tinyLabel}>titles</Text>
                </View>
              </View>
            );
          })}

          <View style={styles.overlapRow}>
            <Ionicons name="git-merge-outline" size={13} color={Colors.textTertiary} />
            <Text style={styles.overlapText}>
              Overlap detected on {data.overlap_titles} titles across your services.
            </Text>
          </View>
        </>
      )}

      {/* Best value for watchlist */}
      {value && value.watchlist_size > 0 && valueRows.length > 0 && (
        <View style={{ marginTop: 32 }} testID="watchlist-value-section">
          <View style={styles.rowStart}>
            <Ionicons name="trophy-outline" size={16} color={Colors.amber} />
            <Text style={[styles.h2, { marginTop: 0, marginBottom: 0 }]}>
              Best value for your watchlist
            </Text>
          </View>
          <Text style={[styles.subtle, { marginTop: 6, marginBottom: 14 }]}>
            Across the {value.watchlist_size} title{value.watchlist_size === 1 ? "" : "s"} you’ve
            saved or watched, here’s where you’d get the most for your money:
          </Text>
          {valueRows.map((s) => (
            <View key={s.service_id} style={styles.card} testID={`value-${s.service_id}`}>
              <View style={styles.summaryRow}>
                <ProviderLogo sid={s.service_id} name={s.name} size={34} radius={9} />
                <View style={{ flex: 1 }}>
                  <Text style={styles.usageName}>{s.name}</Text>
                  <Text style={styles.subtle}>
                    {s.subscribed ? "Subscribed" : "Not subscribed"} · {gbp(s.price_monthly)}/mo
                  </Text>
                </View>
                <View style={{ alignItems: "flex-end" }}>
                  <Text style={styles.usageCount}>{s.titles_count}</Text>
                  <Text style={styles.tinyLabel}>titles</Text>
                </View>
              </View>
              {s.cost_per_title != null && (
                <Text style={[styles.subtle, { marginTop: 8 }]}>
                  ~{gbp(s.cost_per_title)} per title in your list
                </Text>
              )}
              {s.top_titles.length > 0 && (
                <View style={styles.postersRow}>
                  {s.top_titles.map((t) => (
                    <View key={t.id} style={styles.miniPoster}>
                      {t.poster_url ? (
                        <Image
                          source={{ uri: t.poster_url }}
                          style={StyleSheet.absoluteFill}
                          contentFit="cover"
                          transition={150}
                        />
                      ) : null}
                    </View>
                  ))}
                </View>
              )}
            </View>
          ))}
        </View>
      )}
    </ScreenContainer>
  );
}

const styles = StyleSheet.create({
  kicker: {
    fontFamily: "Inter_600SemiBold",
    fontSize: 11,
    letterSpacing: 2,
    textTransform: "uppercase",
    color: Colors.textTertiary,
  },
  h1: {
    fontFamily: "Inter_800ExtraBold",
    fontSize: 30,
    color: Colors.text,
    marginTop: 6,
    lineHeight: 34,
  },
  h2: {
    fontFamily: "Inter_700Bold",
    fontSize: 18,
    color: Colors.text,
    marginTop: 32,
    marginBottom: 12,
  },
  summary: {
    backgroundColor: Colors.surface,
    borderRadius: 24,
    borderWidth: 1,
    borderColor: Colors.border,
    padding: 22,
    marginTop: 24,
  },
  summaryRow: {
    flexDirection: "row",
    alignItems: "flex-end",
    justifyContent: "space-between",
    gap: 12,
  },
  smallLabel: {
    fontFamily: "Inter_600SemiBold",
    fontSize: 10,
    letterSpacing: 1,
    textTransform: "uppercase",
    color: Colors.textTertiary,
    marginBottom: 4,
  },
  big: { fontFamily: "Inter_800ExtraBold", fontSize: 34, color: Colors.text },
  big2: { fontFamily: "Inter_700Bold", fontSize: 22, color: Colors.text },
  subtle: { fontFamily: "Inter_400Regular", fontSize: 12, color: Colors.textTertiary, lineHeight: 17 },
  savingsBanner: {
    flexDirection: "row",
    alignItems: "center",
    gap: 12,
    marginTop: 18,
    paddingTop: 18,
    borderTopWidth: 1,
    borderTopColor: Colors.border,
  },
  savingsIcon: {
    width: 40,
    height: 40,
    borderRadius: 12,
    backgroundColor: "rgba(255,122,24,0.15)",
    alignItems: "center",
    justifyContent: "center",
  },
  savingsTitle: { fontFamily: "Inter_700Bold", fontSize: 15, color: Colors.text },
  card: {
    backgroundColor: Colors.surface,
    borderRadius: 18,
    borderWidth: 1,
    borderColor: Colors.border,
    padding: 16,
    marginBottom: 12,
  },
  rowStart: { flexDirection: "row", alignItems: "flex-start", gap: 12 },
  sugIcon: {
    width: 36,
    height: 36,
    borderRadius: 11,
    backgroundColor: "rgba(255,122,24,0.15)",
    alignItems: "center",
    justifyContent: "center",
  },
  sugHead: { fontFamily: "Inter_700Bold", fontSize: 15, color: Colors.text, marginBottom: 4 },
  cardBody: {
    flex: 1,
    fontFamily: "Inter_400Regular",
    fontSize: 13,
    color: Colors.textSecondary,
    lineHeight: 19,
  },
  insightReason: {
    flexDirection: "row",
    alignItems: "flex-start",
    gap: 9,
    marginTop: 12,
    paddingTop: 12,
    borderTopWidth: 1,
    borderTopColor: Colors.border,
  },
  insightHeadline: {
    fontFamily: "Inter_700Bold",
    fontSize: 13,
    color: Colors.text,
    marginBottom: 3,
  },
  whyShown: {
    fontFamily: "Inter_400Regular",
    fontSize: 11,
    color: Colors.textTertiary,
    lineHeight: 16,
    marginTop: 7,
  },
  usageRow: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 12,
    backgroundColor: Colors.surface,
    borderRadius: 14,
    borderWidth: 1,
    borderColor: Colors.border,
    paddingHorizontal: 16,
    paddingVertical: 12,
    marginBottom: 8,
  },
  usageName: { fontFamily: "Inter_600SemiBold", fontSize: 14, color: Colors.text },
  planTag: {
    fontFamily: "Inter_600SemiBold",
    fontSize: 11,
    color: Colors.amber,
    marginTop: 2,
    marginBottom: 2,
  },
  needsPlan: {
    fontFamily: "Inter_500Medium",
    fontSize: 11,
    color: Colors.saving,
    marginTop: 2,
    marginBottom: 2,
  },
  planPrompt: {
    flexDirection: "row",
    alignItems: "center",
    gap: 12,
    backgroundColor: "rgba(255,122,24,0.10)",
    borderRadius: 16,
    borderWidth: 1,
    borderColor: "rgba(255,122,24,0.30)",
    padding: 16,
    marginTop: 24,
  },
  planPromptTitle: {
    fontFamily: "Inter_700Bold",
    fontSize: 14,
    color: Colors.text,
    marginBottom: 3,
  },
  usageCount: { fontFamily: "Inter_700Bold", fontSize: 15, color: Colors.text },
  tinyLabel: {
    fontFamily: "Inter_500Medium",
    fontSize: 9,
    letterSpacing: 1,
    textTransform: "uppercase",
    color: Colors.textTertiary,
    marginTop: 2,
  },
  overlapRow: { flexDirection: "row", alignItems: "center", gap: 6, marginTop: 14 },
  overlapText: {
    fontFamily: "Inter_400Regular",
    fontSize: 12,
    color: Colors.textTertiary,
    flex: 1,
  },
  postersRow: { flexDirection: "row", gap: 6, marginTop: 12 },
  miniPoster: {
    width: 40,
    height: 56,
    borderRadius: 6,
    overflow: "hidden",
    backgroundColor: Colors.velvet,
  },
});
