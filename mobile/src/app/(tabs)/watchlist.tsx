import { Ionicons } from "@expo/vector-icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import * as Haptics from "expo-haptics";
import { router } from "expo-router";
import { useEffect, useMemo, useState } from "react";
import {
  FlatList,
  Modal,
  Platform,
  Pressable,
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  useWindowDimensions,
  View,
} from "react-native";

import { ListEmpty, ListError, ListLoading } from "@/components/lists/ListStates";
import { PosterCard } from "@/components/lists/PosterCard";
import {
  SCREEN_H_PADDING,
  ScreenContainer,
  useScreenPadding,
} from "@/components/layout/ScreenContainer";
import { Colors } from "@/constants/colors";
import { useAuth } from "@/context/AuthContext";
import { getFriendlyMessage } from "@/lib/api";
import { analytics, EVENTS } from "@/lib/analytics";
import {
  fetchLibrary,
  markWatchlistSeen,
  postUserAction,
  markWatchedThrough,
  markSeasonProgress,
  markSeriesProgress,
  setEpisodeProgress,
  toggleEpisodeProgress,
  LibraryData,
  WatchlistItem,
} from "@/lib/social-api";

type LibraryTab = "watchlist" | "watched";
type TypeTab = "all" | "movie" | "tv";
type Sort = "recent" | "title" | "rating" | "year";

const TYPE_TABS: { id: TypeTab; label: string }[] = [
  { id: "all", label: "All" },
  { id: "movie", label: "Movies" },
  { id: "tv", label: "TV Shows" },
];

const SORTS: { id: Sort; label: string }[] = [
  { id: "recent", label: "Recent" },
  { id: "title", label: "A–Z" },
  { id: "rating", label: "Top rated" },
  { id: "year", label: "Newest" },
];

export default function WatchlistScreen() {
  const { width } = useWindowDimensions();
  const screenPad = useScreenPadding();
  const { refresh: refreshUser, user } = useAuth();
  const userId = user?.user_id;
  const queryClient = useQueryClient();

  const [libraryTab, setLibraryTab] = useState<LibraryTab>("watchlist");
  const [typeTab, setTypeTab] = useState<TypeTab>("all");
  const [sort, setSort] = useState<Sort>("recent");
  const [editing, setEditing] = useState<WatchlistItem | null>(null);
  const [season, setSeason] = useState(1);
  const [episode, setEpisode] = useState(1);

  const {
    data,
    isLoading,
    isError,
    error,
    refetch,
    isRefetching,
  } = useQuery<LibraryData>({ queryKey: ["/library"], queryFn: fetchLibrary });

  useEffect(() => {
    analytics.capture(EVENTS.WATCHLIST_VIEWED, {}, { dedupeKey: "watchlist:view", user });
  }, [userId]);

  // Clear the unseen badge when the tab opens (mirrors web behaviour).
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        await markWatchlistSeen();
        if (!cancelled) await refreshUser();
      } catch {
        // best-effort — badge clears next time
      }
    })();
    return () => {
      cancelled = true;
    };
    // Run once on mount.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const remove = useMutation({
    mutationFn: (id: string) => postUserAction(id, "unsave"),
    onMutate: async (id: string) => {
      await queryClient.cancelQueries({ queryKey: ["/library"] });
      const prev = queryClient.getQueryData<LibraryData>(["/library"]);
      queryClient.setQueryData<LibraryData>(["/library"], (old) => ({
        ...(old || { watchlist: [], watched: [] }),
        watchlist: (old?.watchlist || []).filter((m) => m.id !== id),
      }));
      return { prev };
    },
    onError: (_e, _id, ctx) => {
      if (ctx?.prev) queryClient.setQueryData(["/library"], ctx.prev);
    },
    onSuccess: (_data, id) => {
      analytics.capture(EVENTS.WATCHLIST_ITEM_REMOVED, { content_id: id, source: "watchlist", watchlist_size: items.length - 1 }, { dedupeKey: `watchlist:unsave:${id}`, user });
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ["/library"] });
      refreshUser();
    },
  });
  const progressEdit = useMutation({
    mutationFn: async (op: "cursor" | "through" | "toggle" | "season" | "series") => {
      if (!editing) return;
       const contentId = editing.id;
      if (op === "through") return markWatchedThrough(editing.id, season, episode);
      if (op === "toggle") return toggleEpisodeProgress({ movie_id: editing.id, season, episode });
      if (op === "season") return markSeasonProgress(editing.id, season, episode);
      if (op === "series") return markSeriesProgress(editing.id, season, episode);
       await setEpisodeProgress({ movie_id: editing.id, season, episode, watched: true });
       return { contentId, action: op };
    },
    onSuccess: (result, op) => {
      const contentId = (result as { contentId?: string } | undefined)?.contentId || editing?.id;
      analytics.capture(EVENTS.WATCHLIST_PROGRESS_UPDATED, { content_id: contentId, operation: op, source: "progress" }, { dedupeKey: `watchlist:progress:${contentId}:${op}`, user });
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ["/library"] });
      setEditing(null);
    },
  });
  const unwatch = useMutation({
    mutationFn: (id: string) => postUserAction(id, "unwatched"),
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ["/library"] });
      refreshUser();
    },
  });

  const items = libraryTab === "watched" ? data?.watched ?? [] : data?.watchlist ?? [];
  const progressItems = libraryTab === "watched" ? data?.progress ?? [] : [];
  const inProgressIds = useMemo(
    () => new Set(progressItems.filter(
      (m) => m.completion?.completed === false && m.watched_completed !== true
    ).map((m) => m.id)),
    [progressItems]
  );

  const continueWatching = useMemo(() => {
    let arr = data?.continue_watching ?? [];
    if (typeTab === "movie") arr = arr.filter((m) => m.type !== "tv");
    else if (typeTab === "tv") arr = arr.filter((m) => m.type === "tv");
    return arr;
  }, [data?.continue_watching, typeTab]);
  const needsProgress = useMemo(
    () => (libraryTab === "watched" ? (data?.watched ?? []) : []).filter(
      (m) => m.type === "tv" && !inProgressIds.has(m.id)
        && m.completion?.completed !== true && m.watched_completed !== true
    ),
    [data?.watched, inProgressIds, libraryTab]
  );

  const sorted = useMemo(() => {
    let arr = [...items];
    if (libraryTab === "watched") {
      arr = arr.filter(
        (m) => m.type !== "tv" || m.completion?.completed === true || m.watched_completed === true
      );
    }
    if (typeTab === "movie") arr = arr.filter((m) => m.type !== "tv");
    else if (typeTab === "tv") arr = arr.filter((m) => m.type === "tv");

    if (sort === "title") arr.sort((a, b) => (a.title || "").localeCompare(b.title || ""));
    else if (sort === "rating") arr.sort((a, b) => (b.rating || 0) - (a.rating || 0));
    else if (sort === "year") arr.sort((a, b) => (b.year || 0) - (a.year || 0));
    return arr;
  }, [items, typeTab, sort, libraryTab, inProgressIds]);

  const cardWidth = Math.floor((width - SCREEN_H_PADDING * 2 - 12) / 2);

  const renderCardContent = (item: WatchlistItem, isHorizontal: boolean = false) => {
    const cw = isHorizontal ? 120 : cardWidth;
    const sentiment = item.you_reaction;
    const watchedEpisodes = item.completion?.watched_released_episode_count
      ?? item.completion?.watched_episode_count;
    const eligibleEpisodes = item.completion?.eligible_episode_count;
    const progressPct = Number.isFinite(watchedEpisodes) && Number.isFinite(eligibleEpisodes) && Number(eligibleEpisodes) > 0
      ? Math.min(100, Math.round((Number(watchedEpisodes) / Number(eligibleEpisodes)) * 100))
      : null;
    const isTV = item.type === "tv";
    const currentSeason = (item.seasons as Array<{ season_number?: number; episode_count?: number }> | undefined)
      ?.find((s) => s.season_number === item.progress?.season);
    const progressLabel = item.progress
      ? `S${item.progress.season} E${item.progress.episode}${currentSeason?.episode_count ? ` of ${currentSeason.episode_count}` : ""}`
      : "TV";

    return (
      <View style={[styles.cell, isHorizontal && { width: cw, marginRight: 12, marginBottom: 0 }]}>
        <PosterCard
          title={item.title}
          posterUrl={item.poster_url}
          rating={item.rating}
          subLabel={isTV ? progressLabel : null}
          sentiment={sentiment}
          progressPct={progressPct}
          onPress={() => openTitle(item)}
          width={cw}
          testID={`watchlist-item-${item.id}`}
        />
        {isTV && (
          <Pressable
            style={styles.progressBtn}
            disabled={progressEdit.isPending}
            onPress={() => {
              setEditing(item);
              setSeason(item.progress?.season || 1);
              setEpisode(item.progress?.episode || 1);
            }}
            accessibilityRole="button"
            accessibilityLabel={`Update progress for ${item.title}`}
          >
            <Ionicons name={libraryTab === "watchlist" ? "add-outline" : "play-forward-outline"} size={13} color={Colors.amber} />
            <Text style={styles.progressText}>
              {libraryTab === "watchlist"
                ? "Start tracking"
                : item.progress
                  ? `Update S${item.progress.season} E${item.progress.episode}`
                  : "Update progress"}
            </Text>
          </Pressable>
        )}
        {libraryTab === "watched" && (
          <Pressable style={styles.removeBtn} onPress={() => unwatch.mutate(item.id)}
            disabled={unwatch.isPending} accessibilityRole="button"
            accessibilityLabel={`Mark ${item.title} unwatched`}>
            <Ionicons name="eye-off-outline" size={13} color={Colors.textTertiary} />
            <Text style={styles.removeText}>Unwatch</Text>
          </Pressable>
        )}
        {libraryTab === "watchlist" && <Pressable
          onPress={() => onRemove(item.id)}
          disabled={remove.isPending}
          style={styles.removeBtn}
          accessibilityRole="button"
          accessibilityLabel={`Remove ${item.title} from watchlist`}
          testID={`watchlist-remove-${item.id}`}
        >
          <Ionicons name="trash-outline" size={13} color={Colors.textTertiary} />
          <Text style={styles.removeText}>Remove</Text>
        </Pressable>}
      </View>
    );
  };
  const openTitle = (m: WatchlistItem) => {
    analytics.capture(EVENTS.WATCHLIST_ITEM_OPENED, { content_id: m.id, media_type: m.type, source: "watchlist", watchlist_size: items.length }, { user });
    router.push({
      pathname: "/title/[id]",
      params: { id: m.id, type: m.type === "tv" ? "tv" : "movie" },
    });
  };

  const onRemove = (id: string) => {
    if (remove.isPending) return;
    if (Platform.OS !== "web") Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
    remove.mutate(id);
  };

  const header = (
    <View>
      <View style={styles.headerRow}>
        <Text style={styles.h1}>Library</Text>
        <Text style={styles.count}>{items.length} {libraryTab === "watched" ? "watched" : "saved"}</Text>
      </View>
      {data?.stats && (
        <Text style={styles.stats}>
          {libraryTab === "watchlist" ? (
            `${data.stats.saved ?? 0} saved`
          ) : (
            `${data.stats.watched ?? 0} titles · ${data.stats.watched_episodes ?? 0} episodes · ${
              (() => {
                const hours = Math.floor(data.stats.total_hours || 0);
                const minutes = Math.round(((data.stats.total_hours || 0) - hours) * 60);
                const parts = [];
                if (hours > 0) parts.push(`${hours}h`);
                if (minutes > 0 || parts.length === 0) parts.push(`${minutes}m`);
                return parts.join(" ");
              })()
            } watched${data.stats.total_hours_estimated ? " (est.)" : ""}`
          )}
        </Text>
      )}
      <View style={styles.chipRow}>
        {(["watchlist", "watched"] as LibraryTab[]).map((id) => (
          <Pressable key={id} onPress={() => setLibraryTab(id)}
            style={[styles.chip, libraryTab === id && styles.chipActive]}
            accessibilityRole="tab" accessibilityState={{ selected: libraryTab === id }}>
            <Text style={[styles.chipText, libraryTab === id && styles.chipTextActive]}>
              {id === "watchlist" ? "Watchlist" : "Watched"}
            </Text>
          </Pressable>
        ))}
      </View>
      {libraryTab === "watched" && continueWatching.length > 0 && (
        <View style={styles.continueBox}>
          <Text style={styles.sectionTitle}>Continue Watching</Text>
          <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.continueScroll}>
            {continueWatching.map((m) => (
              <View key={m.id}>
                {renderCardContent(m, true)}
              </View>
            ))}
          </ScrollView>
        </View>
      )}
      {libraryTab === "watched" && needsProgress.length > 0 && typeTab !== "movie" && (
        <View style={styles.continueBox}>
          <Text style={styles.sectionTitle}>Watched · set TV progress</Text>
          <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.continueScroll}>
            {needsProgress.map((m) => <View key={m.id}>{renderCardContent(m, true)}</View>)}
          </ScrollView>
        </View>
      )}
      {libraryTab === "watched" && sorted.length > 0 && (
        <Text style={styles.completedTitle}>Completed</Text>
      )}

      {items.length > 0 && (
        <>
          <View style={styles.chipRow}>
            {TYPE_TABS.map((t) => {
              const active = typeTab === t.id;
              return (
                <Pressable
                  key={t.id}
                  onPress={() => {
                    setTypeTab(t.id);
                    analytics.capture(EVENTS.FILTER_CHANGED, {
                      filter_name: "content_type",
                      selected: true,
                      selected_count: 1,
                      source: "watchlist",
                    }, { user });
                  }}
                  style={[styles.chip, active && styles.chipActive]}
                  accessibilityRole="button"
                  accessibilityLabel={`Show ${t.label}`}
                >
                  <Text style={[styles.chipText, active && styles.chipTextActive]}>
                    {t.label}
                  </Text>
                </Pressable>
              );
            })}
          </View>
          <View style={styles.chipRow}>
            {SORTS.map((s) => {
              const active = sort === s.id;
              return (
                <Pressable
                  key={s.id}
                  onPress={() => {
                    setSort(s.id);
                    analytics.capture(EVENTS.FILTER_CHANGED, {
                      filter_name: "sort",
                      selected: true,
                      selected_count: 1,
                      source: "watchlist",
                    }, { user });
                  }}
                  style={[styles.chipSm, active && styles.chipActive]}
                  accessibilityRole="button"
                  accessibilityLabel={`Sort by ${s.label}`}
                >
                  <Text style={[styles.chipTextSm, active && styles.chipTextActive]}>
                    {s.label}
                  </Text>
                </Pressable>
              );
            })}
          </View>
        </>
      )}
    </View>
  );

  if (isLoading) {
    return (
      <ScreenContainer>
        {header}
        <ListLoading />
      </ScreenContainer>
    );
  }

  if (isError) {
    return (
      <ScreenContainer>
        {header}
        <ListError
          message={getFriendlyMessage(error)}
          onRetry={refetch}
          testID="watchlist-error"
        />
      </ScreenContainer>
    );
  }

  return (
    <>
    <FlatList
      style={styles.container}
      contentContainerStyle={{
        paddingTop: screenPad.paddingTop,
        paddingHorizontal: screenPad.paddingHorizontal,
        paddingBottom: screenPad.paddingBottom,
      }}
      data={sorted}
      keyExtractor={(m) => m.id}
      numColumns={2}
      columnWrapperStyle={{ gap: 12 }}
      ListHeaderComponent={header}
      ListEmptyComponent={
        <ListEmpty
          icon={libraryTab === "watched" ? "eye-outline" : "heart-outline"}
          title={libraryTab === "watched" ? "Nothing watched yet" : "Nothing saved yet"}
          body={libraryTab === "watched"
            ? "Mark titles watched to keep a record of what you've seen."
            : "Swipe right on Discover to save titles for later."}
          action={libraryTab === "watched" ? undefined : { label: "Start swiping", onPress: () => router.push("/(tabs)/discover") }}
        />
      }
      refreshControl={
        <RefreshControl
          refreshing={isRefetching}
          onRefresh={refetch}
          tintColor={Colors.amber}
        />
      }
      renderItem={({ item }) => renderCardContent(item, false)}
    />
    <Modal visible={!!editing} transparent animationType="slide" onRequestClose={() => setEditing(null)}>
      <View style={styles.modalBackdrop}>
        <View style={styles.modalCard}>
          <Text style={styles.sectionTitle}>TV progress</Text>
          <Text style={styles.modalHint}>{editing?.title || ""}</Text>
          <View style={styles.progressInputs}>
            <View style={{ flex: 1 }}>
              <Text style={styles.inputLabel}>Season</Text>
              <TextInput value={String(season)} onChangeText={(v) => setSeason(Math.max(1, Math.min(99, Number(v) || 1)))}
                keyboardType="number-pad" style={styles.input} />
            </View>
            <View style={{ flex: 1 }}>
              <Text style={styles.inputLabel}>Episode</Text>
              <TextInput value={String(episode)} onChangeText={(v) => setEpisode(Math.max(1, Math.min(999, Number(v) || 1)))}
                keyboardType="number-pad" style={styles.input} />
            </View>
          </View>
          <View style={styles.progressSummary}>
            <Text style={styles.progressSummaryTitle}>Watched through S{season} E{episode}</Text>
            <Text style={styles.modalHint}>Choose a season and episode above, then save the progress you want recorded.</Text>
          </View>
          <Pressable style={styles.modalAction} onPress={() => progressEdit.mutate("through")}>
            <Text style={styles.modalActionText}>I’ve watched up to here</Text>
          </Pressable>
          <Pressable style={styles.modalActionAlt} onPress={() => progressEdit.mutate("cursor")}>
            <Text style={styles.modalActionTextAlt}>Set as current episode</Text>
          </Pressable>
          <Pressable style={styles.modalActionAlt} onPress={() => progressEdit.mutate("toggle")}>
            <Text style={styles.modalActionTextAlt}>Toggle just this episode</Text>
          </Pressable>
          <Pressable style={styles.modalActionAlt} onPress={() => progressEdit.mutate("season")}>
            <Text style={styles.modalActionTextAlt}>Mark season up to here</Text>
          </Pressable>
          <Pressable style={styles.modalActionAlt} onPress={() => progressEdit.mutate("series")}>
            <Text style={styles.modalActionTextAlt}>Mark entire show watched</Text>
          </Pressable>
          <Pressable onPress={() => setEditing(null)} style={styles.cancelBtn}>
            <Text style={styles.removeText}>Cancel</Text>
          </Pressable>
        </View>
      </View>
    </Modal>
    </>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: Colors.obsidian },
  headerRow: {
    flexDirection: "row",
    alignItems: "flex-end",
    justifyContent: "space-between",
    marginBottom: 16,
  },
  h1: { fontFamily: "Inter_800ExtraBold", fontSize: 30, color: Colors.text },
  count: { fontFamily: "Inter_500Medium", fontSize: 13, color: Colors.textSecondary },
  stats: { fontFamily: "Inter_400Regular", fontSize: 11, color: Colors.textTertiary, marginTop: -10, marginBottom: 14 },
  chipRow: { flexDirection: "row", gap: 8, marginBottom: 12, flexWrap: "wrap" },
  chip: {
    paddingHorizontal: 14,
    paddingVertical: 7,
    borderRadius: 999,
    borderWidth: 1,
    borderColor: Colors.border,
  },
  chipSm: {
    paddingHorizontal: 12,
    paddingVertical: 6,
    borderRadius: 999,
    borderWidth: 1,
    borderColor: Colors.border,
  },
  chipActive: { backgroundColor: Colors.amber, borderColor: Colors.amber },
  chipText: { fontFamily: "Inter_600SemiBold", fontSize: 12, color: Colors.textSecondary },
  chipTextSm: { fontFamily: "Inter_500Medium", fontSize: 11, color: Colors.textSecondary },
  chipTextActive: { color: "#0B0500" },
  cell: { flex: 1, marginBottom: 16 },
  removeBtn: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 5,
    marginTop: 8,
    paddingVertical: 6,
  },
  removeText: { fontFamily: "Inter_500Medium", fontSize: 12, color: Colors.textTertiary },
  progressBtn: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 5,
    marginTop: 6,
    paddingVertical: 7,
    borderRadius: 8,
    backgroundColor: Colors.surface,
    borderWidth: 1,
    borderColor: Colors.border,
  },
  progressText: { fontFamily: "Inter_500Medium", fontSize: 10, color: Colors.amber },
  continueBox: {
    marginBottom: 20,
    marginTop: 8,
  },
  continueScroll: {
    paddingRight: 12,
  },
  sectionTitle: { fontFamily: "Inter_700Bold", fontSize: 16, color: Colors.text, marginBottom: 12 },
  completedTitle: { fontFamily: "Inter_700Bold", fontSize: 18, color: Colors.text, marginTop: 4, marginBottom: 12 },
  continueText: { fontFamily: "Inter_400Regular", fontSize: 12, color: Colors.textSecondary, lineHeight: 20 },
  modalBackdrop: { flex: 1, justifyContent: "flex-end", backgroundColor: "rgba(0,0,0,0.7)" },
  modalCard: { backgroundColor: Colors.surface, borderTopLeftRadius: 24, borderTopRightRadius: 24, padding: 20, paddingBottom: 32 },
  modalHint: { fontFamily: "Inter_400Regular", fontSize: 13, color: Colors.textSecondary, marginBottom: 14 },
  progressInputs: { flexDirection: "row", gap: 12 },
  inputLabel: { fontFamily: "Inter_600SemiBold", fontSize: 11, color: Colors.textTertiary, marginBottom: 5 },
  input: { backgroundColor: Colors.velvet, color: Colors.text, borderWidth: 1, borderColor: Colors.border, borderRadius: 10, padding: 10, fontSize: 16 },
  progressSummary: { backgroundColor: "rgba(255,122,24,0.09)", borderWidth: 1, borderColor: "rgba(255,122,24,0.22)", borderRadius: 14, padding: 14, marginTop: 14, marginBottom: 6 },
  progressSummaryTitle: { color: Colors.text, fontFamily: "Inter_700Bold", fontSize: 14, marginBottom: 5 },
  modalAction: { backgroundColor: Colors.amber, borderRadius: 11, padding: 12, alignItems: "center", marginTop: 8 },
  modalActionText: { color: Colors.obsidian, fontFamily: "Inter_700Bold", fontSize: 13 },
  modalActionAlt: { backgroundColor: "rgba(255,255,255,0.05)", borderRadius: 11, padding: 12, alignItems: "center", marginTop: 8 },
  modalActionTextAlt: { color: Colors.text, fontFamily: "Inter_600SemiBold", fontSize: 13 },
  cancelBtn: { alignItems: "center", padding: 12, marginTop: 4 },
});
