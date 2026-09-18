import { Ionicons } from "@expo/vector-icons";
import { useQuery } from "@tanstack/react-query";
import { Image } from "expo-image";
import { router, useLocalSearchParams } from "expo-router";
import { useEffect, useMemo, useState } from "react";
import {
  Pressable,
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  useWindowDimensions,
  View,
} from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { ListError, ListLoading } from "@/components/lists/ListStates";
import { PosterCard } from "@/components/lists/PosterCard";
import { Colors } from "@/constants/colors";
import { getFriendlyMessage, resolveImageUrl } from "@/lib/api";
import { CompareData, CompareMovie, fetchCompare } from "@/lib/social-api";
import { analytics, EVENTS } from "@/lib/analytics";

type Tab =
  | "saved_both"
  | "saved_you"
  | "saved_friend"
  | "watched_both"
  | "watched_you"
  | "watched_friend"
  | "for_you_both";

export default function CompareScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const friendId = String(id);
  const insets = useSafeAreaInsets();
  const { width } = useWindowDimensions();
  const [tab, setTab] = useState<Tab>("saved_both");
  const [primary, setPrimary] = useState<"saved" | "watched" | "recs">("saved");
  useEffect(() => {
    analytics.capture(EVENTS.FRIEND_COMPARE_OPENED, { compare_mode: "friend" });
  }, [friendId]);

  const { data, isLoading, isError, error, refetch, isRefetching } = useQuery<CompareData>({
    queryKey: ["/share/compare", friendId],
    queryFn: () => fetchCompare(friendId),
    retry: (count, err) => {
      // 403 = not friends; don't retry.
      const status = (err as { response?: { status?: number } })?.response?.status;
      return status !== 403 && count < 1;
    },
  });

  const cardWidth = Math.floor((width - 20 * 2 - 10 * 2) / 3);

  const REACTION_META: Record<string, { symbol: string; label: string }> = {
    loved: { symbol: "❤️", label: "loved it" },
    liked: { symbol: "👍", label: "liked it" },
    neutral: { symbol: "😐", label: "thought it was okay" },
    disliked: { symbol: "👎", label: "didn't like it" },
  };

  const reactionMeta = (value: string | null | undefined) => {
    return REACTION_META[String(value || "").toLowerCase()] || null;
  };

  const tabs = useMemo(() => {
    if (!data) return [];
    const themFirst = (data.them?.name || "Them").split(" ")[0];
    const saved = data.saved || { both: data.overlap, you: data.only_me, friend: data.only_them };
    const watched = data.watched || { both: data.watched_both || [], you: [], friend: [] };
    return primary === "saved"
      ? [
          { id: "saved_both" as Tab, label: "Saved both", count: (saved.both || []).length },
          { id: "saved_you" as Tab, label: "Saved you", count: (saved.you || []).length },
          { id: "saved_friend" as Tab, label: `Saved ${themFirst}`, count: (saved.friend || []).length },
        ]
      : primary === "watched"
        ? [
            { id: "watched_both" as Tab, label: "Watched both", count: (watched.both || []).length },
            { id: "watched_you" as Tab, label: "Watched you", count: (watched.you || []).length },
            { id: "watched_friend" as Tab, label: `Watched ${themFirst}`, count: (watched.friend || []).length },
          ]
        : [{ id: "for_you_both" as Tab, label: "For You Both", count: data.recommendations.length }];
  }, [data, primary]);

  const openTitle = (m: CompareMovie) => {
    analytics.capture(EVENTS.FRIEND_OVERLAP_ITEM_OPENED, { content_id: m.id });
    router.push({
      pathname: "/title/[id]",
      params: { id: m.id, type: m.type === "tv" ? "tv" : "movie" },
    });
  };

  const back = (
    <Pressable
      onPress={() => router.back()}
      style={styles.back}
      accessibilityRole="button"
      accessibilityLabel="Back to friends"
      hitSlop={8}
    >
      <Ionicons name="arrow-back" size={18} color={Colors.textSecondary} />
      <Text style={styles.backText}>Friends</Text>
    </Pressable>
  );

  if (isLoading) {
    return (
      <View style={[styles.container, { paddingTop: insets.top + 8, paddingHorizontal: 20 }]}>
        {back}
        <ListLoading />
      </View>
    );
  }

  if (isError || !data) {
    const status = (error as { response?: { status?: number } })?.response?.status;
    return (
      <View style={[styles.container, { paddingTop: insets.top + 8, paddingHorizontal: 20 }]}>
        {back}
        <ListError
          message={
            status === 403
              ? "You're not sharing watchlists with this person."
              : getFriendlyMessage(error)
          }
          onRetry={refetch}
          testID="compare-error"
        />
      </View>
    );
  }

  const saved = data.saved || { both: data.overlap, you: data.only_me, friend: data.only_them };
  const watched = data.watched || { both: data.watched_both || [], you: [], friend: [] };
  const listByTab: Record<Tab, CompareMovie[]> = {
    saved_both: saved.both || [], saved_you: saved.you || [], saved_friend: saved.friend || [],
    watched_both: watched.both || [], watched_you: watched.you || [], watched_friend: watched.friend || [],
    for_you_both: data.recommendations,
  };
  const list = listByTab[tab];

  const emptyCopy: Record<Tab, { title: string; body: string }> = {
    saved_both: {
      title: "No shared picks yet",
      body: "Keep swiping — overlap appears the moment you both save the same title.",
    },
    saved_you: {
      title: "No titles saved only by you",
      body: "Your individual saved picks will appear here.",
    },
    saved_friend: {
      title: `No titles saved only by ${data.them.name}`,
      body: "Your friend's individual saved picks will appear here.",
    },
    watched_both: {
      title: "Nothing watched by both yet",
      body: "Titles you've both marked as watched will show up here.",
    },
    watched_you: { title: "No titles watched only by you", body: "Your watched history will appear here." },
    watched_friend: { title: `No titles watched only by ${data.them.name}`, body: "Their watched history will appear here." },
    for_you_both: {
      title: "Building recommendations",
      body: "Keep using the app — smart picks land here as we learn both your tastes.",
    },
  };

  return (
    <ScrollView
      style={styles.container}
      contentContainerStyle={{
        paddingTop: insets.top + 8,
        paddingHorizontal: 20,
        paddingBottom: insets.bottom + 40,
      }}
      refreshControl={
        <RefreshControl refreshing={isRefetching} onRefresh={refetch} tintColor={Colors.amber} />
      }
    >
      {back}

      <View style={styles.avatarsRow}>
        <View style={styles.avatarStack}>
          <Avatar name={data.you?.name} picture={data.you?.picture} />
          <View style={{ marginLeft: -12 }}>
            <Avatar name={data.them?.name} picture={data.them?.picture} />
          </View>
        </View>
      </View>

      <Text style={styles.kicker}>You & {data.them.name}</Text>
      <Text style={styles.h1}>
        {data.overlap.length > 0
          ? `You both saved ${data.overlap.length} title${data.overlap.length === 1 ? "" : "s"}.`
          : "No overlap — yet."}
      </Text>

      {data.pick_tonight && (
        <Pressable
          onPress={() => openTitle(data.pick_tonight as CompareMovie)}
          style={({ pressed }) => [styles.pickCard, pressed && { opacity: 0.9 }]}
          accessibilityRole="button"
          accessibilityLabel={`Open ${data.pick_tonight.title}`}
          testID="pick-tonight-cta"
        >
          <View style={styles.pickPoster}>
            {data.pick_tonight.poster_url ? (
              <Image
                source={{ uri: data.pick_tonight.poster_url }}
                style={StyleSheet.absoluteFill}
                contentFit="cover"
                transition={200}
              />
            ) : (
              <Ionicons name="film-outline" size={22} color={Colors.textTertiary} />
            )}
          </View>
          <View style={{ flex: 1, minWidth: 0 }}>
            <View style={styles.pickTag}>
              <Ionicons name="sparkles" size={12} color={Colors.amber} />
              <Text style={styles.pickTagText}>
                {data.overlap.length > 0 ? "Pick tonight" : "What you'll both love"}
              </Text>
            </View>
            <Text style={styles.pickTitle} numberOfLines={2}>
              {data.pick_tonight.title}
            </Text>
            {(data.pick_tonight.genres?.length ?? 0) > 0 && (
              <Text style={styles.pickSub} numberOfLines={1}>
                {data.pick_tonight.genres!.join(" · ")}
              </Text>
            )}
            <Text style={styles.pickCta}>Open details →</Text>
          </View>
        </Pressable>
      )}

      <View style={styles.primaryTabs}>
        {([
          ["saved", "Watchlists"],
          ["watched", "Watched"],
          ["recs", "For You Both"],
        ] as const).map(([id, label]) => (
          <Pressable key={id} onPress={() => {
            const nextTab = id === "saved" ? "saved_both" : id === "watched" ? "watched_both" : "for_you_both";
            setPrimary(id);
            setTab(nextTab);
            analytics.capture(EVENTS.FRIEND_COMPARE_TAB_VIEWED, { compare_mode: id });
          }}
            style={[styles.primaryTab, primary === id && styles.tabActive]}
            accessibilityRole="tab" accessibilityState={{ selected: primary === id }}>
            <Text style={[styles.tabLabel, primary === id && styles.tabLabelActive]}>{label}</Text>
          </Pressable>
        ))}
      </View>
      <ScrollView
        horizontal
        showsHorizontalScrollIndicator={false}
        style={styles.tabsScroll}
        contentContainerStyle={styles.tabsRow}
      >
        {tabs.map((t) => {
          const active = tab === t.id;
          return (
            <Pressable
              key={t.id}
              onPress={() => {
                setTab(t.id);
                analytics.capture(EVENTS.FRIEND_COMPARE_TAB_VIEWED, { compare_mode: t.id });
              }}
              style={[styles.tab, active && styles.tabActive]}
              accessibilityRole="button"
              accessibilityLabel={`${t.label}, ${t.count} titles`}
              testID={`compare-tab-${t.id}`}
            >
              <Text style={[styles.tabLabel, active && styles.tabLabelActive]} numberOfLines={1}>
                {t.label}
              </Text>
              <Text style={[styles.tabCount, active && styles.tabCountActive]}>{t.count}</Text>
            </Pressable>
          );
        })}
      </ScrollView>

      {list.length === 0 ? (
        <View style={styles.emptyCard}>
          <Ionicons name="heart-outline" size={22} color={Colors.amber} />
          <Text style={styles.emptyTitle}>{emptyCopy[tab].title}</Text>
          <Text style={styles.emptyBody}>{emptyCopy[tab].body}</Text>
        </View>
      ) : (
        <View style={styles.grid}>
          {list.map((m) => {
            const friendReaction = reactionMeta(data.sentiment?.friend?.[m.id]);
            const yourReaction = reactionMeta(data.sentiment?.you?.[m.id]);
            const banner = friendReaction
              ? { ...friendReaction, who: data.them.name.split(" ")[0] }
              : yourReaction
              ? { ...yourReaction, who: "You" }
              : null;

            return (
            <View key={m.id} style={{ width: cardWidth }}>
              <PosterCard
                title={m.title}
                posterUrl={m.poster_url}
                rating={m.rating}
                reactionBanner={banner}
                onPress={() => openTitle(m)}
                width={cardWidth}
                testID={`compare-card-${m.id}`}
              />
              {(data.progress?.you?.[m.id] || data.progress?.friend?.[m.id]) && (
                <Text style={styles.compareMeta} numberOfLines={2}>
                  {data.progress?.you?.[m.id]
                    ? `You: S${data.progress.you[m.id].season} E${data.progress.you[m.id].episode}`
                    : ""}
                  {data.progress?.friend?.[m.id]
                    ? ` · ${data.them.name.split(" ")[0]}: S${data.progress.friend[m.id].season} E${data.progress.friend[m.id].episode}`
                    : ""}
                </Text>
              )}
              {tab === "for_you_both" && m.reason ? (
                <Text
                  style={styles.recReason}
                  numberOfLines={2}
                  testID={`compare-reason-${m.id}`}
                >
                  {m.reason}
                </Text>
              ) : null}
            </View>
          )})}
        </View>
      )}
    </ScrollView>
  );
}

function Avatar({ name, picture }: { name?: string | null; picture?: string | null }) {
  const initial = (name || "?").slice(0, 1).toUpperCase();
  const [imgError, setImgError] = useState(false);
  const resolved = resolveImageUrl(picture);
  const showImage = !!resolved && !imgError;
  return (
    <View style={styles.avatar}>
      {showImage ? (
        <Image
          source={{ uri: resolved as string }}
          style={styles.avatarImg}
          contentFit="cover"
          onError={() => setImgError(true)}
        />
      ) : (
        <Text style={styles.avatarText}>{initial}</Text>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: Colors.obsidian },
  back: { flexDirection: "row", alignItems: "center", gap: 6, marginBottom: 16 },
  backText: { fontFamily: "Inter_500Medium", fontSize: 14, color: Colors.textSecondary },
  avatarsRow: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    marginBottom: 14,
  },
  avatarStack: { flexDirection: "row", alignItems: "center" },
  liveRow: { flexDirection: "row", alignItems: "center", gap: 6 },
  liveDot: { width: 6, height: 6, borderRadius: 3, backgroundColor: Colors.amber },
  liveText: {
    fontFamily: "Inter_600SemiBold",
    fontSize: 10,
    letterSpacing: 1,
    textTransform: "uppercase",
    color: Colors.textTertiary,
  },
  kicker: {
    fontFamily: "Inter_600SemiBold",
    fontSize: 11,
    letterSpacing: 2,
    textTransform: "uppercase",
    color: Colors.textTertiary,
  },
  h1: {
    fontFamily: "Inter_800ExtraBold",
    fontSize: 26,
    color: Colors.text,
    marginTop: 6,
    lineHeight: 30,
  },
  pickCard: {
    flexDirection: "row",
    gap: 14,
    backgroundColor: Colors.surface,
    borderRadius: 22,
    borderWidth: 1,
    borderColor: "rgba(255,122,24,0.25)",
    padding: 16,
    marginTop: 20,
  },
  pickPoster: {
    width: 72,
    height: 104,
    borderRadius: 12,
    overflow: "hidden",
    backgroundColor: Colors.velvet,
    alignItems: "center",
    justifyContent: "center",
  },
  pickTag: { flexDirection: "row", alignItems: "center", gap: 6, marginBottom: 8 },
  pickTagText: {
    fontFamily: "Inter_700Bold",
    fontSize: 10,
    letterSpacing: 1.5,
    textTransform: "uppercase",
    color: Colors.amber,
  },
  pickTitle: { fontFamily: "Inter_700Bold", fontSize: 16, color: Colors.text, lineHeight: 20 },
  pickSub: { fontFamily: "Inter_400Regular", fontSize: 12, color: Colors.textTertiary, marginTop: 4 },
  pickCta: { fontFamily: "Inter_500Medium", fontSize: 13, color: Colors.textSecondary, marginTop: 8 },
  tabsScroll: {
    marginTop: 22,
    backgroundColor: "rgba(255,255,255,0.03)",
    borderRadius: 16,
    borderWidth: 1,
    borderColor: Colors.border,
    flexGrow: 0,
  },
  primaryTabs: { flexDirection: "row", gap: 6, marginTop: 20, padding: 5, backgroundColor: "rgba(255,255,255,0.03)", borderRadius: 16, borderWidth: 1, borderColor: Colors.border },
  primaryTab: { flex: 1, alignItems: "center", paddingVertical: 10, borderRadius: 12 },
  tabsRow: {
    flexDirection: "row",
    gap: 6,
    padding: 5,
  },
  tab: { alignItems: "center", paddingVertical: 9, paddingHorizontal: 14, borderRadius: 12 },
  tabActive: { backgroundColor: Colors.amber },
  tabLabel: { fontFamily: "Inter_600SemiBold", fontSize: 11, color: Colors.textSecondary },
  tabLabelActive: { color: "#0B0500" },
  tabCount: { fontFamily: "Inter_500Medium", fontSize: 10, color: Colors.textTertiary, marginTop: 2 },
  tabCountActive: { color: "rgba(11,5,0,0.7)" },
  grid: { flexDirection: "row", flexWrap: "wrap", gap: 10, marginTop: 18 },
  recReason: {
    fontFamily: "Inter_400Regular",
    fontSize: 10,
    color: Colors.amber,
    marginTop: 4,
    lineHeight: 14,
  },
  compareMeta: {
    fontFamily: "Inter_400Regular",
    fontSize: 10,
    color: Colors.textTertiary,
    marginTop: 5,
    lineHeight: 14,
  },
  emptyCard: {
    alignItems: "center",
    gap: 6,
    backgroundColor: Colors.surface,
    borderRadius: 18,
    borderWidth: 1,
    borderColor: Colors.border,
    padding: 24,
    marginTop: 18,
  },
  emptyTitle: { fontFamily: "Inter_700Bold", fontSize: 14, color: Colors.text, marginTop: 4 },
  emptyBody: {
    fontFamily: "Inter_400Regular",
    fontSize: 12,
    color: Colors.textTertiary,
    textAlign: "center",
    lineHeight: 18,
  },
  avatar: {
    width: 40,
    height: 40,
    borderRadius: 20,
    backgroundColor: "rgba(255,122,24,0.2)",
    borderWidth: 2,
    borderColor: Colors.obsidian,
    alignItems: "center",
    justifyContent: "center",
    overflow: "hidden",
  },
  avatarImg: { width: "100%", height: "100%" },
  avatarText: { fontFamily: "Inter_700Bold", fontSize: 16, color: Colors.amber },
});
