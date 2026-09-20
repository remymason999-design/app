import { Ionicons } from "@expo/vector-icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import * as Haptics from "expo-haptics";
import { router, useFocusEffect } from "expo-router";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  FlatList,
  Alert,
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
  Image,
} from "react-native";
import { KeyboardAwareScrollView } from "react-native-keyboard-controller";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { ListEmpty, ListError, ListLoading } from "@/components/lists/ListStates";
import { PosterCard } from "@/components/lists/PosterCard";
import {
  SCREEN_H_PADDING,
  ScreenContainer,
  useScreenPadding,
} from "@/components/layout/ScreenContainer";
import { Colors } from "@/constants/colors";
import { useAuth } from "@/context/AuthContext";
import { getFriendlyMessage, resolveImageUrl } from "@/lib/api";
import { analytics, EVENTS } from "@/lib/analytics";
import {
  fetchLibrary,
  markWatchlistSeen,
  postUserAction,
  markWatchedThrough,
  markSeriesProgress,
  LibraryData,
  WatchlistItem,
} from "@/lib/social-api";

type LibraryTab = "watchlist" | "watched";
type TypeTab = "all" | "movie" | "tv";
type Sort = "recent" | "title" | "rating" | "year";

const TYPE_TABS: { id: TypeTab; label: string }[] = [
  { id: "all", label: "All" },
  { id: "movie", label: "Movies" },
  { id: "tv", label: "TV" },
];

const SORTS: { id: Sort; label: string }[] = [
  { id: "recent", label: "Recently added" },
  { id: "title", label: "Title (A–Z)" },
  { id: "rating", label: "Highest rated" },
  { id: "year", label: "Newest released" },
];

export default function WatchlistScreen() {
  const { width } = useWindowDimensions();
  const insets = useSafeAreaInsets();
  const screenPad = useScreenPadding();
  const { refresh: refreshUser, user } = useAuth();
  const userId = user?.user_id;
  const queryClient = useQueryClient();

  const [libraryTab, setLibraryTab] = useState<LibraryTab>("watchlist");
  const [typeTab, setTypeTab] = useState<TypeTab>("all");
  const [sort, setSort] = useState<Sort>("recent");
  const [editing, setEditing] = useState<WatchlistItem | null>(null);
  const [seasonInput, setSeasonInput] = useState("1");
  const [episodeInput, setEpisodeInput] = useState("1");
  const [progressError, setProgressError] = useState<string | null>(null);
  const [page, setPage] = useState(1);
  const listRef = useRef<FlatList<WatchlistItem>>(null);
  const hasFocusedOnce = useRef(false);
  const PAGE_SIZE = 12;
  const season = Math.max(1, Math.min(99, Number.parseInt(seasonInput, 10) || 1));
  const episode = Math.max(1, Math.min(999, Number.parseInt(episodeInput, 10) || 1));

  const {
    data,
    isLoading,
    isError,
    error,
    refetch,
    isRefetching,
  } = useQuery<LibraryData>({ queryKey: ["/library"], queryFn: fetchLibrary });

  useFocusEffect(
    useCallback(() => {
      if (hasFocusedOnce.current) {
        void refetch();
      } else {
        hasFocusedOnce.current = true;
      }
    }, [refetch]),
  );

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
    mutationFn: async (op: "through" | "series") => {
      if (!editing) return;
      if (op === "through") return markWatchedThrough(editing.id, season, episode);
      if (op === "series") return markSeriesProgress(editing.id, season, episode);
    },
    onMutate: () => setProgressError(null),
    onSuccess: (result, op) => {
      const contentId = (result as { contentId?: string } | undefined)?.contentId || editing?.id;
      analytics.capture(EVENTS.WATCHLIST_PROGRESS_UPDATED, { content_id: contentId, operation: op, source: "progress" }, { dedupeKey: `watchlist:progress:${contentId}:${op}`, user });
      queryClient.invalidateQueries({ queryKey: ["/library"] });
      setEditing(null);
    },
    onError: (error) => setProgressError(getFriendlyMessage(error)),
  });
  const unwatch = useMutation({
    mutationFn: (id: string) => postUserAction(id, "unwatched"),
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ["/library"] });
      refreshUser();
    },
  });

  const items = useMemo(
    () => libraryTab === "watched" ? data?.watched ?? [] : data?.watchlist ?? [],
    [data?.watched, data?.watchlist, libraryTab],
  );
  const continueWatching = useMemo(() => {
    // Merge tracked and not-yet-tracked watched TV into one unfinished section.
    // Completion remains server-owned; native only classifies the returned rows.
    const seen = new Set<string>();
    let arr = [...(data?.continue_watching ?? []), ...(data?.watched ?? [])].filter((m) => {
      const unfinished = m.type === "tv"
        && m.completion?.completed !== true
        && m.watched_completed !== true;
      if (!unfinished || seen.has(m.id)) return false;
      seen.add(m.id);
      return true;
    });
    if (typeTab === "movie") arr = arr.filter((m) => m.type !== "tv");
    else if (typeTab === "tv") arr = arr.filter((m) => m.type === "tv");
    return arr;
  }, [data?.continue_watching, data?.watched, typeTab]);

  const sorted = useMemo(() => {
    let arr = [...items];
    if (libraryTab === "watched") {
      // A watched TV title belongs in Completed only when the server says all
      // eligible episodes are complete. Movies are completed when watched.
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
  }, [items, typeTab, sort, libraryTab]);

  useEffect(() => {
    setPage(1);
  }, [libraryTab, typeTab, sort]);
  const pageCount = Math.max(1, Math.ceil(sorted.length / PAGE_SIZE));
  const visibleItems = sorted.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);
  useEffect(() => {
    if (page > pageCount) setPage(pageCount);
  }, [page, pageCount]);

  const changePage = (nextPage: number) => {
    setPage(Math.max(1, Math.min(pageCount, nextPage)));
    requestAnimationFrame(() => {
      if (visibleItems.length > 0) {
        listRef.current?.scrollToIndex({ index: 0, animated: false, viewPosition: 0 });
      }
    });
  };

  const cardWidth = Math.floor((width - SCREEN_H_PADDING * 2 - 12) / 2);
  const activeSortLabel = SORTS.find((option) => option.id === sort)?.label ?? SORTS[0].label;

  const chooseSort = () => {
    Alert.alert(
      "Sort Library",
      undefined,
      [
        ...SORTS.map((option) => ({
          text: `${option.id === sort ? "✓ " : ""}${option.label}`,
          onPress: () => {
            setSort(option.id);
            setPage(1);
            analytics.capture(EVENTS.FILTER_CHANGED, {
              filter_name: "sort",
              selected: true,
              selected_count: 1,
              source: "watchlist",
            }, { user });
          },
        })),
        { text: "Cancel", style: "cancel" as const },
      ],
    );
  };

  const renderCardContent = (item: WatchlistItem, isHorizontal: boolean = false) => {
    const cw = isHorizontal ? Math.floor(width * 0.4) : cardWidth;
    const sentiment = item.you_reaction;
    const isTV = item.type === "tv";
    const watchedEpisodes = item.completion?.watched_released_episode_count
      ?? item.completion?.watched_episode_count;
    const eligibleEpisodes = item.completion?.eligible_episode_count;
    const progressPct = isTV && Number.isFinite(item.completion?.progress_pct)
      ? Math.min(100, Math.max(0, Math.round(Number(item.completion?.progress_pct))))
      : isTV && Number.isFinite(watchedEpisodes) && Number.isFinite(eligibleEpisodes) && Number(eligibleEpisodes) > 0
        ? Math.min(100, Math.round((Number(watchedEpisodes) / Number(eligibleEpisodes)) * 100))
        : null;
    const progressLabel = item.progress
      ? `S${item.progress.season} E${item.progress.episode}`
      : "TV";
    const watchedLabel = isTV && Number.isFinite(watchedEpisodes) && Number.isFinite(eligibleEpisodes)
      ? `${watchedEpisodes} of ${eligibleEpisodes} episodes${progressPct != null ? ` · ${progressPct}%` : ""}`
      : null;
    const movieRuntime = !isTV && Number.isFinite(item.runtime) && Number(item.runtime) > 0
      ? `${Math.floor(Number(item.runtime) / 60)}h ${Number(item.runtime) % 60}m`
      : null;
    const hasProgress = !!item.progress;

    return (
      <View style={[styles.cell, isHorizontal && { width: cw, marginRight: 12, marginBottom: 0 }]}>
        <PosterCard
          title={item.title}
          posterUrl={item.poster_url}
          rating={item.rating}
          subLabel={isTV ? progressLabel : movieRuntime}
          progressLabel={watchedLabel}
          sentiment={sentiment}
          progressPct={progressPct}
          overlayMetadata
          onPress={() => openTitle(item)}
          width={cw}
          testID={`watchlist-item-${item.id}`}
        />
        {isTV && (
          <Pressable
            style={[styles.progressBtn, { backgroundColor: Colors.amber }]}
            disabled={progressEdit.isPending}
            onPress={() => {
              setEditing(item);
              setSeasonInput(String(item.progress?.season || 1));
              setEpisodeInput(String(item.progress?.episode || 1));
            }}
            accessibilityRole="button"
            accessibilityLabel={`Update progress for ${item.title}`}
          >
            <Ionicons name={libraryTab === "watched" || hasProgress ? "play" : "add"} size={14} color={Colors.obsidian} />
            <Text style={[styles.progressText, { color: Colors.obsidian }]}>
              {libraryTab === "watched" || hasProgress ? "Update progress" : "Start tracking"}
            </Text>
          </Pressable>
        )}
        {libraryTab === "watched" && (
          <Pressable
            style={styles.moreBtn}
            onPress={() => Alert.alert(`${item.title} actions`, undefined, [
              { text: "Cancel", style: "cancel" },
              { text: "Unwatch", style: "destructive", onPress: () => unwatch.mutate(item.id) },
            ])}
            disabled={unwatch.isPending}
            accessibilityRole="button"
            accessibilityLabel={`More actions for ${item.title}`}
            accessibilityHint="Opens actions including Unwatch"
          >
            <Ionicons name="ellipsis-horizontal" size={18} color={Colors.textTertiary} />
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
      <View style={styles.headerBlock}>
        <View style={styles.headerTopRow}>
          <Text style={styles.eyebrow}>Your Collection</Text>
          <Pressable
            style={styles.profileAvatar}
            onPress={() => router.push("/profile")}
            accessibilityRole="button"
            accessibilityLabel="Open profile"
            hitSlop={8}
          >
            {user?.picture ? (
              <Image source={{ uri: resolveImageUrl(user.picture) || undefined }} style={styles.avatarImg} />
            ) : (
              <Text style={styles.avatarText}>
                {(String(user?.name || user?.email || "?").trim()[0] || "?").toUpperCase()}
              </Text>
            )}
          </Pressable>
        </View>
        <Text style={styles.h1}>Library</Text>
      </View>

      <View style={styles.segmentControl}>
        {(["watchlist", "watched"] as LibraryTab[]).map((id) => (
          <Pressable key={id} onPress={() => { setLibraryTab(id); setPage(1); }}
            style={[styles.segmentBtn, libraryTab === id && styles.segmentBtnActive]}
            accessibilityRole="tab" accessibilityState={{ selected: libraryTab === id }}>
            <Ionicons
              name={id === "watchlist" ? "heart-outline" : "eye-outline"}
              size={17}
              color={libraryTab === id ? Colors.obsidian : Colors.textSecondary}
            />
            <Text style={[styles.segmentText, libraryTab === id && styles.segmentTextActive]}>
              {id === "watchlist" ? "Watchlist" : "Watched"}
            </Text>
          </Pressable>
        ))}
      </View>

      {libraryTab === "watched" && data?.stats && (
        <View style={styles.viewingSection}>
          <Text style={styles.viewingEyebrow}>Your viewing</Text>
          <View style={styles.statsGrid}>
          <View style={styles.statCard}>
            <Ionicons name="eye-outline" size={18} color={Colors.amber} />
            <Text style={styles.statValue}>{data.stats.watched ?? 0}</Text>
            <Text style={styles.statLabel}>Titles watched</Text>
          </View>
          <View style={styles.statCard}>
            <Ionicons name="time-outline" size={18} color={Colors.amber} />
            <Text style={styles.statValue}>
              {(() => {
                const hours = Math.floor(data.stats.total_hours || 0);
                const minutes = Math.round(((data.stats.total_hours || 0) - hours) * 60);
                if (!hours) return `${minutes}m`;
                return minutes ? `${hours}h ${minutes}m` : `${hours}h`;
              })()}
            </Text>
            <Text style={styles.statLabel}>Total watch time</Text>
          </View>
          <View style={styles.statCard}>
            <Ionicons name="play-outline" size={18} color={Colors.amber} />
            <Text style={styles.statValue}>{data.stats.watched_episodes ?? 0}</Text>
            <Text style={styles.statLabel}>Episodes watched</Text>
          </View>
          </View>
        </View>
      )}
      {libraryTab === "watched" && continueWatching.length > 0 && (
        <View style={styles.continueBox}>
          <View style={styles.sectionHeadingRow}>
            <View>
              <Text style={styles.sectionEyebrow}>In progress</Text>
              <View style={styles.sectionTitleRow}>
                <Ionicons name="play" size={16} color={Colors.amber} />
                <Text style={styles.sectionTitle}>Continue watching</Text>
              </View>
            </View>
            <Text style={styles.sectionCount}>{continueWatching.length} show{continueWatching.length === 1 ? "" : "s"}</Text>
          </View>
          <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.continueScroll}>
            {continueWatching.map((m) => (
              <View key={m.id}>
                {renderCardContent(m, true)}
              </View>
            ))}
          </ScrollView>
        </View>
      )}
      {items.length > 0 && (
        <View style={styles.filterRow}>
          <View style={styles.filterTabs}>
            {TYPE_TABS.map((t) => {
              const active = typeTab === t.id;
              return (
                <Pressable
                  key={t.id}
                  onPress={() => {
                    setTypeTab(t.id);
                    setPage(1);
                    analytics.capture(EVENTS.FILTER_CHANGED, {
                      filter_name: "content_type",
                      selected: true,
                      selected_count: 1,
                      source: "watchlist",
                    }, { user });
                  }}
                  style={[styles.filterTab, active && styles.filterTabActive]}
                  accessibilityRole="button"
                  accessibilityLabel={`Show ${t.label}`}
                >
                  <Text style={[styles.filterTabText, active && styles.filterTabTextActive]}>
                    {t.label}
                  </Text>
                </Pressable>
              );
            })}
          </View>
          <Pressable
            style={styles.sortButton}
            onPress={chooseSort}
            accessibilityRole="button"
            accessibilityLabel={`Sort Library, currently ${activeSortLabel}`}
          >
            <Text style={styles.sortBtnText} numberOfLines={1}>{activeSortLabel}</Text>
            <Ionicons name="chevron-down" size={13} color={Colors.textSecondary} />
          </Pressable>
        </View>
      )}
      {libraryTab === "watched" && sorted.length > 0 && (
        <View style={styles.completedHeading}>
          <Text style={styles.sectionEyebrow}>Finished</Text>
          <View style={styles.sectionTitleRow}>
            <Ionicons name="checkmark" size={20} color={Colors.amber} />
            <Text style={styles.completedTitle}>Completed</Text>
          </View>
        </View>
      )}
    </View>
  );

  if (isLoading) {
    return (
      <ScreenContainer style={{ paddingTop: insets.top + 18 }}>
        {header}
        <ListLoading />
      </ScreenContainer>
    );
  }

  if (isError) {
    return (
      <ScreenContainer style={{ paddingTop: insets.top + 18 }}>
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
      ref={listRef}
      style={styles.container}
      contentContainerStyle={{
        paddingTop: insets.top + 18,
        paddingHorizontal: screenPad.paddingHorizontal,
        paddingBottom: screenPad.paddingBottom,
      }}
      data={visibleItems}
      keyExtractor={(m) => m.id}
      numColumns={2}
      columnWrapperStyle={{ gap: 12 }}
      ListHeaderComponent={header}
      ListEmptyComponent={
        libraryTab === "watched" && continueWatching.length > 0
          ? null
          : <ListEmpty
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
      ListFooterComponent={pageCount > 1 ? (
        <View style={styles.pagination} testID="library-pagination">
          <Pressable
            disabled={page <= 1}
            onPress={() => changePage(page - 1)}
            style={[styles.pageButton, page <= 1 && styles.pageButtonDisabled]}
            accessibilityLabel="Previous page"
          >
            <Text style={styles.pageButtonText}>Previous</Text>
          </Pressable>
          <Text style={styles.pageLabel}>Page {page} of {pageCount}</Text>
          <Pressable
            disabled={page >= pageCount}
            onPress={() => changePage(page + 1)}
            style={[styles.pageButton, page >= pageCount && styles.pageButtonDisabled]}
            accessibilityLabel="Next page"
          >
            <Text style={styles.pageButtonText}>Next</Text>
          </Pressable>
        </View>
      ) : null}
    />
    <Modal
      visible={!!editing}
      transparent
      animationType="slide"
      onRequestClose={() => {
        if (progressEdit.isPending) return;
        setProgressError(null);
        setEditing(null);
      }}
    >
      <View style={styles.modalBackdrop}>
        <KeyboardAwareScrollView
          style={styles.modalCard}
          contentContainerStyle={[styles.modalCardContent, { paddingBottom: insets.bottom + 24 }]}
          bottomOffset={insets.bottom + 20}
          keyboardShouldPersistTaps="handled"
          showsVerticalScrollIndicator={false}
        >
          <View style={styles.modalHeader}>
            <View style={styles.modalHeaderCopy}>
              <Text style={styles.modalEyebrow}>Track every episode</Text>
              <Text style={styles.modalTitle}>Update progress</Text>
              <Text style={styles.modalSubtitle}>{editing?.title || ""}</Text>
            </View>
            <Pressable
              disabled={progressEdit.isPending}
              onPress={() => {
                setProgressError(null);
                setEditing(null);
              }}
              style={styles.modalClose}
              accessibilityRole="button"
              accessibilityLabel="Close progress editor"
              hitSlop={8}
            >
              <Ionicons name="close" size={24} color={Colors.textSecondary} />
            </Pressable>
          </View>
          <View style={styles.progressInputs}>
            <View style={{ flex: 1 }}>
              <Text style={styles.inputLabel}>Season</Text>
              <View style={styles.stepper}>
                <Pressable onPress={() => setSeasonInput(String(Math.max(1, season - 1)))} style={styles.stepperButton} accessibilityLabel="Previous season">
                  <Text style={styles.stepperText}>−</Text>
                </Pressable>
                <TextInput
                  value={seasonInput}
                  onChangeText={(value) => setSeasonInput(value.replace(/\D/g, "").slice(0, 2))}
                  onBlur={() => setSeasonInput(String(season))}
                  keyboardType="number-pad"
                  selectTextOnFocus
                  style={[styles.input, { flex: 1 }]}
                  accessibilityLabel="Season number"
                />
                <Pressable onPress={() => setSeasonInput(String(Math.min(99, season + 1)))} style={styles.stepperButton} accessibilityLabel="Next season">
                  <Text style={styles.stepperText}>+</Text>
                </Pressable>
              </View>
            </View>
            <View style={{ flex: 1 }}>
              <Text style={styles.inputLabel}>Episode</Text>
              <View style={styles.stepper}>
                <Pressable onPress={() => setEpisodeInput(String(Math.max(1, episode - 1)))} style={styles.stepperButton} accessibilityLabel="Previous episode">
                  <Text style={styles.stepperText}>−</Text>
                </Pressable>
                <TextInput
                  value={episodeInput}
                  onChangeText={(value) => setEpisodeInput(value.replace(/\D/g, "").slice(0, 3))}
                  onBlur={() => setEpisodeInput(String(episode))}
                  keyboardType="number-pad"
                  selectTextOnFocus
                  style={[styles.input, { flex: 1 }]}
                  accessibilityLabel="Episode number"
                />
                <Pressable onPress={() => setEpisodeInput(String(Math.min(999, episode + 1)))} style={styles.stepperButton} accessibilityLabel="Next episode">
                  <Text style={styles.stepperText}>+</Text>
                </Pressable>
              </View>
            </View>
          </View>
          <View style={styles.progressSummary}>
            <Text style={styles.progressSummaryTitle}>Watched through S{season}E{episode}</Text>
            <Text style={styles.progressSummaryText}>
              This updates your Continue Watching position, episode total and watch-time estimate.
            </Text>
          </View>
          {progressError ? <Text style={styles.progressError}>{progressError}</Text> : null}
          <Pressable style={[styles.modalAction, progressEdit.isPending && styles.actionDisabled]} disabled={progressEdit.isPending} onPress={() => progressEdit.mutate("through")}>
            <Text style={styles.modalActionText}>{progressEdit.isPending ? "Saving…" : "Save progress"}</Text>
          </Pressable>
          <Pressable style={[styles.modalActionAlt, progressEdit.isPending && styles.actionDisabled]} disabled={progressEdit.isPending} onPress={() => progressEdit.mutate("series")}>
            <Text style={styles.modalActionTextAlt}>Mark currently available episodes watched</Text>
          </Pressable>
        </KeyboardAwareScrollView>
      </View>
    </Modal>
    </>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: Colors.obsidian },
  headerBlock: {
    marginBottom: 20,
  },
  headerTopRow: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    marginBottom: 2,
  },
  eyebrow: {
    fontFamily: "Inter_500Medium",
    fontSize: 11,
    color: Colors.textTertiary,
    textTransform: "uppercase",
    letterSpacing: 2.2,
  },
  profileAvatar: {
    width: 42,
    height: 42,
    borderRadius: 21,
    backgroundColor: Colors.amber,
    alignItems: "center",
    justifyContent: "center",
  },
  avatarImg: { width: 42, height: 42, borderRadius: 21 },
  avatarText: { fontFamily: "Inter_800ExtraBold", fontSize: 16, color: Colors.obsidian },
  h1: {
    fontFamily: "Inter_800ExtraBold",
    fontSize: 40,
    lineHeight: 44,
    color: Colors.text,
    letterSpacing: -1.3,
  },
  stats: {
    fontFamily: "Inter_400Regular",
    fontSize: 14,
    color: Colors.textSecondary,
    marginTop: 3,
  },
  segmentControl: {
    flexDirection: "row",
    backgroundColor: "rgba(255,255,255,0.025)",
    padding: 4,
    borderRadius: 17,
    borderWidth: 1,
    borderColor: Colors.border,
    marginBottom: 24,
  },
  segmentBtn: {
    flex: 1,
    minHeight: 52,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 8,
    borderRadius: 13,
  },
  segmentBtnActive: { backgroundColor: Colors.amber },
  segmentText: { fontFamily: "Inter_600SemiBold", fontSize: 14, color: Colors.textSecondary },
  segmentTextActive: { color: Colors.obsidian },
  viewingSection: {
    marginBottom: 28,
  },
  viewingEyebrow: {
    fontFamily: "Inter_500Medium",
    fontSize: 10,
    color: Colors.textTertiary,
    textTransform: "uppercase",
    letterSpacing: 2,
    marginBottom: 12,
  },
  statsGrid: {
    flexDirection: "row",
    gap: 8,
  },
  statCard: {
    flex: 1,
    minHeight: 126,
    backgroundColor: "rgba(255,255,255,0.045)",
    borderWidth: 1,
    borderColor: Colors.border,
    borderRadius: 16,
    padding: 12,
    alignItems: "flex-start",
  },
  statValue: {
    fontFamily: "Inter_800ExtraBold",
    fontSize: 21,
    lineHeight: 25,
    color: Colors.text,
    marginTop: "auto",
  },
  statLabel: {
    fontFamily: "Inter_500Medium",
    fontSize: 9,
    lineHeight: 11,
    color: Colors.textTertiary,
    textTransform: "uppercase",
    letterSpacing: 0.6,
    marginTop: 7,
  },
  filterRow: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 8,
    flexWrap: "wrap",
    marginBottom: 22,
  },
  filterTabs: { flexDirection: "row", gap: 6, flexShrink: 1 },
  filterTab: {
    paddingHorizontal: 14,
    paddingVertical: 8,
    borderRadius: 20,
    borderWidth: 1,
    borderColor: Colors.border,
  },
  filterTabActive: { backgroundColor: Colors.amber, borderColor: Colors.amber },
  filterTabText: { fontFamily: "Inter_600SemiBold", fontSize: 12, color: Colors.textSecondary },
  filterTabTextActive: { color: Colors.obsidian },
  sortButton: {
    maxWidth: 126,
    minHeight: 34,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 5,
    paddingHorizontal: 10,
    borderRadius: 10,
    borderWidth: 1,
    borderColor: Colors.border,
    backgroundColor: "rgba(255,255,255,0.035)",
  },
  sortBtnText: {
    flexShrink: 1,
    fontFamily: "Inter_500Medium",
    fontSize: 11,
    color: Colors.textSecondary,
  },
  cell: { flex: 1, marginBottom: 24 },
  removeBtn: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 5,
    marginTop: 8,
    paddingVertical: 8,
    backgroundColor: Colors.surface,
    borderRadius: 8,
  },
  moreBtn: {
    alignSelf: "flex-end",
    alignItems: "center",
    justifyContent: "center",
    marginTop: 8,
    padding: 5,
    minWidth: 30,
    minHeight: 30,
  },
  removeText: { fontFamily: "Inter_600SemiBold", fontSize: 12, color: Colors.textSecondary },
  progressBtn: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 8,
    minHeight: 44,
    marginTop: 12,
    paddingVertical: 10,
    borderRadius: 12,
  },
  progressText: { fontFamily: "Inter_700Bold", fontSize: 12 },
  continueBox: {
    marginBottom: 32,
  },
  continueScroll: {
    paddingRight: 12,
    gap: 16,
  },
  sectionHeadingRow: {
    flexDirection: "row",
    alignItems: "flex-end",
    justifyContent: "space-between",
    marginBottom: 14,
  },
  sectionTitleRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 7,
  },
  sectionEyebrow: {
    fontFamily: "Inter_500Medium",
    fontSize: 10,
    color: Colors.amber,
    textTransform: "uppercase",
    letterSpacing: 2,
    marginBottom: 5,
  },
  sectionTitle: {
    fontFamily: "Inter_800ExtraBold",
    fontSize: 23,
    lineHeight: 27,
    color: Colors.text,
    letterSpacing: -0.6,
  },
  sectionCount: {
    fontFamily: "Inter_400Regular",
    fontSize: 12,
    color: Colors.textTertiary,
    marginBottom: 3,
  },
  completedHeading: {
    marginBottom: 14,
  },
  completedTitle: {
    fontFamily: "Inter_800ExtraBold",
    fontSize: 23,
    lineHeight: 27,
    color: Colors.text,
    letterSpacing: -0.6,
  },
  continueText: { fontFamily: "Inter_400Regular", fontSize: 12, color: Colors.textSecondary, lineHeight: 20 },
  modalBackdrop: { flex: 1, justifyContent: "flex-end", backgroundColor: "rgba(0,0,0,0.7)" },
  modalCard: {
    maxHeight: "92%",
    backgroundColor: Colors.surface,
    borderTopLeftRadius: 24,
    borderTopRightRadius: 24,
  },
  modalCardContent: { padding: 20 },
  modalHeader: { flexDirection: "row", alignItems: "flex-start", justifyContent: "space-between", marginBottom: 28 },
  modalHeaderCopy: { flex: 1, paddingRight: 16 },
  modalEyebrow: {
    fontFamily: "Inter_500Medium",
    fontSize: 10,
    lineHeight: 14,
    color: Colors.amber,
    textTransform: "uppercase",
    letterSpacing: 2,
    marginBottom: 5,
  },
  modalTitle: {
    fontFamily: "Inter_800ExtraBold",
    fontSize: 27,
    lineHeight: 31,
    color: Colors.text,
    letterSpacing: -0.7,
  },
  modalSubtitle: { fontFamily: "Inter_400Regular", fontSize: 14, color: Colors.textSecondary, marginTop: 3 },
  modalClose: {
    width: 42,
    height: 42,
    borderRadius: 21,
    backgroundColor: "rgba(255,255,255,0.04)",
    alignItems: "center",
    justifyContent: "center",
  },
  progressInputs: { flexDirection: "row", gap: 12 },
  inputLabel: {
    fontFamily: "Inter_500Medium",
    fontSize: 10,
    color: Colors.textTertiary,
    textTransform: "uppercase",
    letterSpacing: 0.8,
    marginBottom: 8,
  },
  input: { backgroundColor: Colors.velvet, color: Colors.text, borderWidth: 1, borderColor: Colors.border, borderRadius: 12, padding: 12, fontSize: 16 },
  progressSummary: { backgroundColor: "rgba(255,122,24,0.09)", borderWidth: 1, borderColor: "rgba(255,122,24,0.22)", borderRadius: 16, padding: 16, marginTop: 24, marginBottom: 10 },
  progressSummaryTitle: { color: Colors.text, fontFamily: "Inter_700Bold", fontSize: 15, marginBottom: 5 },
  progressSummaryText: { color: Colors.textSecondary, fontFamily: "Inter_400Regular", fontSize: 13, lineHeight: 18 },
  modalAction: { backgroundColor: Colors.amber, borderRadius: 16, minHeight: 56, alignItems: "center", justifyContent: "center", marginTop: 10 },
  modalActionText: { color: Colors.obsidian, fontFamily: "Inter_700Bold", fontSize: 15 },
  modalActionAlt: { backgroundColor: "rgba(255,255,255,0.04)", borderWidth: 1, borderColor: Colors.border, borderRadius: 14, minHeight: 50, alignItems: "center", justifyContent: "center", marginTop: 10, paddingHorizontal: 14 },
  modalActionTextAlt: { color: Colors.text, fontFamily: "Inter_500Medium", fontSize: 14, textAlign: "center" },
  actionDisabled: { opacity: 0.5 },
  progressError: {
    color: Colors.danger,
    fontFamily: "Inter_500Medium",
    fontSize: 12,
    lineHeight: 17,
    marginBottom: 10,
  },
  pagination: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 12, paddingVertical: 12, backgroundColor: Colors.obsidian },
  pageButton: { paddingHorizontal: 12, paddingVertical: 8, borderRadius: 8, backgroundColor: Colors.surface, borderWidth: 1, borderColor: Colors.border },
  pageButtonDisabled: { opacity: 0.35 },
  pageButtonText: { fontFamily: "Inter_600SemiBold", fontSize: 12, color: Colors.text },
  pageLabel: { fontFamily: "Inter_600SemiBold", fontSize: 12, color: Colors.textSecondary },
  stepper: { flexDirection: "row", alignItems: "center", gap: 4 },
  stepperButton: { width: 36, height: 46, alignItems: "center", justifyContent: "center", borderRadius: 11, backgroundColor: Colors.velvet, borderWidth: 1, borderColor: Colors.border },
  stepperText: { color: Colors.amber, fontSize: 22, lineHeight: 24 },
});
