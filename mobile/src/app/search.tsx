import { Ionicons } from "@expo/vector-icons";
import { Stack, router } from "expo-router";
import { useEffect, useRef, useState } from "react";
import {
  ActivityIndicator,
  FlatList,
  Image,
  Keyboard,
  Pressable,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { Colors } from "@/constants/colors";
import { analytics, EVENTS } from "@/lib/analytics";
import { useAuth } from "@/context/AuthContext";
import {
  SearchResult,
  engage,
  formatRuntime,
  searchTitles,
} from "@/lib/content-api";

const MAX_QUERY_LEN = 200;
const DEBOUNCE_MS = 350;

const LABELS: Record<string, { text: string; color: string; bg: string }> = {
  included: { text: "Included", color: Colors.success, bg: "rgba(34,197,94,0.12)" },
  elsewhere: { text: "Available elsewhere", color: "#7DD3FC", bg: "rgba(56,189,248,0.12)" },
  rent_or_buy: { text: "Rent or buy", color: Colors.amber, bg: "rgba(255,122,24,0.12)" },
  unavailable: { text: "Unavailable", color: Colors.textTertiary, bg: "rgba(255,255,255,0.05)" },
};

export default function Search() {
  const insets = useSafeAreaInsets();
  const { user } = useAuth();
  const inputRef = useRef<TextInput>(null);

  const [q, setQ] = useState("");
  const [results, setResults] = useState<SearchResult[]>([]);
  const [fallback, setFallback] = useState(false);
  const [loading, setLoading] = useState(false);
  const [errored, setErrored] = useState(false);
  const [total, setTotal] = useState(0);

  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const genRef = useRef(0);
  const lastQueryRef = useRef("");

  useEffect(() => {
    const t = setTimeout(() => inputRef.current?.focus(), 250);
    return () => clearTimeout(t);
  }, []);

  const runSearch = (raw: string) => {
    const trimmed = raw.trim();
    if (debounceRef.current) clearTimeout(debounceRef.current);
    if (abortRef.current) {
      try {
        abortRef.current.abort();
      } catch {
        // ignore
      }
      abortRef.current = null;
    }
    if (!trimmed) {
      setResults([]);
      setFallback(false);
      setErrored(false);
      setTotal(0);
      setLoading(false);
      return;
    }
    debounceRef.current = setTimeout(async () => {
      const myGen = ++genRef.current;
      const controller = new AbortController();
      abortRef.current = controller;
      lastQueryRef.current = trimmed;
      setLoading(true);
      setErrored(false);
      try {
        const r = await searchTitles(trimmed, { signal: controller.signal });
        if (myGen !== genRef.current) return;
        setResults(r.results);
        setFallback(r.fallback);
        setTotal(typeof r.total === "number" ? r.total : r.results.length);
        analytics.capture(EVENTS.SEARCH_PERFORMED, {
          query_length: trimmed.length,
          result_count: r.results.length,
          fallback: r.fallback,
          has_results: r.results.length > 0,
        }, { dedupeKey: `search:${trimmed.toLowerCase()}:${r.results.length}`, user });
        if (r.results.length === 0) {
          analytics.capture(EVENTS.SEARCH_NO_RESULTS, { result_count: 0 }, { dedupeKey: `search-no-results:${trimmed.toLowerCase()}`, user });
        }
      } catch (err) {
        const canceled =
          (err as { code?: string; name?: string })?.code === "ERR_CANCELED" ||
          (err as { name?: string })?.name === "CanceledError";
        if (canceled || myGen !== genRef.current) return;
        setResults([]);
        setErrored(true);
      } finally {
        if (myGen === genRef.current) setLoading(false);
        if (abortRef.current === controller) abortRef.current = null;
      }
    }, DEBOUNCE_MS);
  };

  const onChangeText = (text: string) => {
    const clipped = text.slice(0, MAX_QUERY_LEN);
    setQ(clipped);
    runSearch(clipped);
  };

  const clear = () => {
    setQ("");
    runSearch("");
    inputRef.current?.focus();
  };

  const retry = () => runSearch(q);

  const openTitle = (m: SearchResult) => {
    Keyboard.dismiss();
    engage(m.id, "search_click");
    analytics.capture(EVENTS.SEARCH_RESULT_SELECTED, { selected_content_id: m.id }, { user });
    router.push({ pathname: "/title/[id]", params: { id: m.id, type: m.type || "movie" } });
  };

  const trimmed = q.trim();

  const renderItem = ({ item }: { item: SearchResult }) => {
    const runtime = formatRuntime(item.runtime);
    const seasons = (item.seasons || []).length;
    const label = item.availability_label ? LABELS[item.availability_label] : undefined;
    const metaBits =
      item.type === "tv"
        ? `TV · ${seasons || 1} season${(seasons || 1) > 1 ? "s" : ""}`
        : runtime || "Movie";
    return (
      <Pressable
        onPress={() => openTitle(item)}
        style={({ pressed }) => [styles.card, pressed && { opacity: 0.75 }]}
        accessibilityRole="button"
        accessibilityLabel={`Open ${item.title || "title"}`}
      >
        <View style={styles.posterWrap}>
          {item.poster_url ? (
            <Image source={{ uri: item.poster_url }} style={styles.poster} resizeMode="cover" />
          ) : (
            <View style={[styles.poster, styles.posterFallback]}>
              <Ionicons name="film-outline" size={22} color={Colors.textTertiary} />
            </View>
          )}
        </View>
        <View style={styles.cardBody}>
          <Text style={styles.cardTitle} numberOfLines={1}>
            {item.title || "Untitled"}
          </Text>
          <View style={styles.cardMeta}>
            {typeof item.rating === "number" && item.rating > 0 ? (
              <>
                <Ionicons name="star" size={11} color={Colors.amber} />
                <Text style={styles.cardMetaText}>{item.rating.toFixed(1)}</Text>
                <Text style={styles.cardMetaDot}>·</Text>
              </>
            ) : null}
            {item.year ? (
              <>
                <Text style={styles.cardMetaText}>{item.year}</Text>
                <Text style={styles.cardMetaDot}>·</Text>
              </>
            ) : null}
            <Text style={styles.cardMetaText}>{metaBits}</Text>
          </View>
          {item.overview ? (
            <Text style={styles.cardOverview} numberOfLines={2}>
              {item.overview}
            </Text>
          ) : null}
          {label ? (
            <View style={[styles.labelChip, { backgroundColor: label.bg }]}>
              <Text style={[styles.labelText, { color: label.color }]}>{label.text}</Text>
            </View>
          ) : null}
        </View>
      </Pressable>
    );
  };

  const listHeader = (
    <>
      {fallback && results.length > 0 ? (
        <View style={styles.fallbackBox}>
          <Ionicons name="sparkles-outline" size={16} color={Colors.amber} />
          <Text style={styles.fallbackText}>
            We couldn&apos;t find an exact match. Here are similar titles you might love instead.
          </Text>
        </View>
      ) : null}
      {!loading && !errored && results.length > 0 ? (
        <Text style={styles.total}>
          {total > 0 ? `${total.toLocaleString()} ` : `${results.length} `}
          result{(total || results.length) === 1 ? "" : "s"} for &quot;{trimmed}&quot;
        </Text>
      ) : null}
    </>
  );

  const renderEmpty = () => {
    if (loading) {
      return (
        <View style={styles.stateBox}>
          <ActivityIndicator color={Colors.amber} />
          <Text style={styles.stateText}>Searching…</Text>
        </View>
      );
    }
    if (errored) {
      return (
        <View style={styles.stateBox}>
          <Ionicons name="cloud-offline-outline" size={40} color={Colors.textSecondary} />
          <Text style={styles.stateTitle}>Search couldn&apos;t load</Text>
          <Text style={styles.stateText}>Check your connection and try again.</Text>
          <Pressable
            onPress={retry}
            style={({ pressed }) => [styles.retryBtn, pressed && { opacity: 0.85 }]}
            accessibilityRole="button"
            accessibilityLabel="Try search again"
          >
            <Text style={styles.retryText}>Try again</Text>
          </Pressable>
        </View>
      );
    }
    if (trimmed && results.length === 0) {
      return (
        <View style={styles.stateBox}>
          <Ionicons name="search-outline" size={40} color={Colors.textTertiary} />
          <Text style={styles.stateTitle}>No results for &quot;{trimmed}&quot;</Text>
          <Text style={styles.stateText}>Try a different title, actor, or genre.</Text>
        </View>
      );
    }
    if (!trimmed) {
      return (
        <View style={styles.stateBox}>
          <Ionicons name="search" size={40} color={Colors.textTertiary} />
          <Text style={styles.stateTitle}>Search WatchSmart</Text>
          <Text style={styles.stateText}>Find films, TV shows, actors, or genres.</Text>
        </View>
      );
    }
    return null;
  };

  return (
    <View style={styles.root}>
      <Stack.Screen options={{ headerShown: false }} />
      {/* Header */}
      <View style={[styles.header, { paddingTop: insets.top + 8 }]}>
        <Pressable
          onPress={() => router.back()}
          style={({ pressed }) => [styles.backBtn, pressed && { opacity: 0.7 }]}
          accessibilityRole="button"
          accessibilityLabel="Go back"
          hitSlop={8}
        >
          <Ionicons name="arrow-back" size={22} color={Colors.text} />
        </Pressable>
        <View style={styles.searchBox}>
          <Ionicons name="search" size={16} color={Colors.textTertiary} />
          <TextInput
            ref={inputRef}
            value={q}
            onChangeText={onChangeText}
            placeholder="Title, actor, or genre…"
            placeholderTextColor={Colors.textTertiary}
            style={styles.input}
            maxLength={MAX_QUERY_LEN}
            autoCorrect={false}
            autoCapitalize="none"
            returnKeyType="search"
            onSubmitEditing={() => Keyboard.dismiss()}
            accessibilityLabel="Search titles, actors, or genres"
          />
          {q ? (
            <Pressable
              onPress={clear}
              hitSlop={8}
              accessibilityRole="button"
              accessibilityLabel="Clear search"
            >
              <Ionicons name="close-circle" size={18} color={Colors.textTertiary} />
            </Pressable>
          ) : null}
        </View>
      </View>

      <FlatList
        data={results}
        keyExtractor={(item) => item.id}
        renderItem={renderItem}
        ListHeaderComponent={listHeader}
        ListEmptyComponent={renderEmpty}
        keyboardShouldPersistTaps="handled"
        keyboardDismissMode="on-drag"
        contentContainerStyle={[
          styles.listContent,
          { paddingBottom: insets.bottom + 24 },
          results.length === 0 && styles.listContentEmpty,
        ]}
        showsVerticalScrollIndicator={false}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: Colors.obsidian },
  header: {
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
    paddingHorizontal: 16,
    paddingBottom: 12,
    backgroundColor: Colors.obsidian,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: Colors.border,
  },
  backBtn: {
    width: 40,
    height: 40,
    borderRadius: 20,
    alignItems: "center",
    justifyContent: "center",
  },
  searchBox: {
    flex: 1,
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    backgroundColor: Colors.surface,
    borderWidth: 1,
    borderColor: Colors.border,
    borderRadius: 999,
    paddingHorizontal: 14,
    height: 44,
  },
  input: {
    flex: 1,
    fontFamily: "Inter_500Medium",
    fontSize: 15,
    color: Colors.text,
    padding: 0,
  },
  listContent: { paddingHorizontal: 16, paddingTop: 14 },
  listContentEmpty: { flexGrow: 1 },
  total: {
    fontFamily: "Inter_500Medium",
    fontSize: 12,
    color: Colors.textTertiary,
    marginBottom: 12,
  },
  card: {
    flexDirection: "row",
    gap: 12,
    backgroundColor: Colors.surface,
    borderWidth: 1,
    borderColor: Colors.border,
    borderRadius: 16,
    padding: 10,
    marginBottom: 10,
  },
  posterWrap: {
    width: 62,
    height: 93,
    borderRadius: 10,
    overflow: "hidden",
    backgroundColor: Colors.velvet,
  },
  poster: { width: "100%", height: "100%" },
  posterFallback: { alignItems: "center", justifyContent: "center" },
  cardBody: { flex: 1, minWidth: 0 },
  cardTitle: { fontFamily: "Inter_700Bold", fontSize: 15, color: Colors.text },
  cardMeta: { flexDirection: "row", alignItems: "center", gap: 4, marginTop: 4 },
  cardMetaText: { fontFamily: "Inter_400Regular", fontSize: 12, color: Colors.textSecondary },
  cardMetaDot: { fontFamily: "Inter_400Regular", fontSize: 12, color: Colors.textTertiary },
  cardOverview: {
    fontFamily: "Inter_400Regular",
    fontSize: 12,
    color: Colors.textTertiary,
    marginTop: 5,
    lineHeight: 17,
  },
  labelChip: {
    alignSelf: "flex-start",
    borderRadius: 999,
    paddingHorizontal: 8,
    paddingVertical: 3,
    marginTop: 7,
  },
  labelText: { fontFamily: "Inter_600SemiBold", fontSize: 10 },
  fallbackBox: {
    flexDirection: "row",
    gap: 10,
    backgroundColor: Colors.surface,
    borderWidth: 1,
    borderColor: Colors.border,
    borderRadius: 14,
    padding: 12,
    marginBottom: 14,
  },
  fallbackText: { flex: 1, fontFamily: "Inter_400Regular", fontSize: 13, color: Colors.textSecondary, lineHeight: 18 },
  stateBox: { flex: 1, alignItems: "center", justifyContent: "center", gap: 10, paddingHorizontal: 32, paddingVertical: 60 },
  stateTitle: { fontFamily: "Inter_700Bold", fontSize: 17, color: Colors.text, textAlign: "center", marginTop: 2 },
  stateText: { fontFamily: "Inter_400Regular", fontSize: 14, color: Colors.textSecondary, textAlign: "center" },
  retryBtn: {
    marginTop: 8,
    backgroundColor: Colors.surface,
    borderWidth: 1,
    borderColor: Colors.border,
    borderRadius: 14,
    paddingHorizontal: 22,
    paddingVertical: 11,
  },
  retryText: { fontFamily: "Inter_600SemiBold", fontSize: 14, color: Colors.text },
});
