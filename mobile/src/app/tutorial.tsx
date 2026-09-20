import { Ionicons } from "@expo/vector-icons";
import * as Haptics from "expo-haptics";
import { router, useLocalSearchParams } from "expo-router";
import { useRef, useState } from "react";
import {
  ActivityIndicator,
  NativeScrollEvent,
  NativeSyntheticEvent,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  useWindowDimensions,
  View,
} from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { Colors } from "@/constants/colors";
import { analytics, EVENTS } from "@/lib/analytics";
import { useAuth } from "@/context/AuthContext";
import { updatePreferences } from "@/lib/onboarding-api";

interface GestureRow {
  icon: keyof typeof Ionicons.glyphMap;
  label: string;
  detail: string;
  tint: string;
}

interface TutorialPage {
  key: string;
  eyebrow: string;
  title: string;
  body: string;
  rows: GestureRow[];
}

const PAGES: TutorialPage[] = [
  {
    key: "discover",
    eyebrow: "Discover",
    title: "Find something worth watching",
    body: "Swipe through titles you can actually watch on your services. Every action teaches WatchSmart what to show next.",
    rows: [
      {
        icon: "arrow-forward",
        label: "Swipe right to Save",
        detail: "Adds it to your watchlist for later.",
        tint: Colors.success,
      },
      {
        icon: "arrow-back",
        label: "Swipe left to Skip",
        detail: "Not interested — we won't show it again.",
        tint: Colors.textSecondary,
      },
      {
        icon: "checkmark-done",
        label: "Watched",
        detail: "Rate something you've already seen.",
        tint: Colors.amber,
      },
      {
        icon: "arrow-undo",
        label: "Rewind",
        detail: "Made a mistake? Undo your last swipe.",
        tint: Colors.textSecondary,
      },
    ],
  },
  {
    key: "recs",
    eyebrow: "Personalise",
    title: "Better recommendations",
    body: "Tell WatchSmart what you loved, liked or disliked. The more you rate, the sharper your feed gets.",
    rows: [
      {
        icon: "heart",
        label: "Loved / Liked",
        detail: "Pushes more titles like this to the top.",
        tint: Colors.amber,
      },
      {
        icon: "thumbs-down",
        label: "Disliked",
        detail: "Steers your feed away from this kind of thing.",
        tint: Colors.danger,
      },
      {
        icon: "information-circle",
        label: "Watched isn't liked",
        detail: "Marking a title watched does NOT count as liking it — rate it separately.",
        tint: Colors.textSecondary,
      },
    ],
  },
  {
    key: "together",
    eyebrow: "Together",
    title: "Watch together",
    body: "Compare taste with friends and land on something you'll both enjoy tonight.",
    rows: [
      {
        icon: "people",
        label: "Shared saved titles",
        detail: "See the titles you and a friend have both saved.",
        tint: Colors.amber,
      },
      {
        icon: "sparkles",
        label: "For you both",
        detail: "New recommendations picked for your combined taste — not just the overlap.",
        tint: Colors.success,
      },
    ],
  },
  {
    key: "tv",
    eyebrow: "Library",
    title: "Track every episode",
    body: "Keep up with your TV shows, log the season and episode you're on, and WatchSmart will track your progress and total watch time.",
    rows: [
      {
        icon: "play-forward",
        label: "S1 E6 · Update progress",
        detail: "A clear progress bar keeps your place.",
        tint: Colors.amber,
      },
      {
        icon: "checkmark-done",
        label: "Watched through here",
        detail: "Mark a show watched up to your current episode.",
        tint: Colors.success,
      },
      {
        icon: "pie-chart",
        label: "39h watched",
        detail: "See real watch time from the episodes you log.",
        tint: Colors.textSecondary,
      },
    ],
  },
  {
    key: "savings",
    eyebrow: "Save",
    title: "Spend less",
    body: "Tell us your exact streaming plans and we'll track what you're really paying.",
    rows: [
      {
        icon: "pricetag",
        label: "Pick your exact plans",
        detail: "Choose the tier you're on so your spend is accurate.",
        tint: Colors.amber,
      },
      {
        icon: "trending-down",
        label: "Trim what you don't use",
        detail: "WatchSmart flags services you may not be getting value from.",
        tint: Colors.success,
      },
    ],
  },
];

export default function TutorialScreen() {
  const params = useLocalSearchParams<{ replay?: string }>();
  const isReplay = params.replay === "1";
  const { setUser } = useAuth();
  const insets = useSafeAreaInsets();
  const { width } = useWindowDimensions();
  const scrollRef = useRef<ScrollView>(null);
  const [page, setPage] = useState(0);
  const [finishing, setFinishing] = useState(false);

  const goTo = (p: number) => {
    const clamped = Math.max(0, Math.min(PAGES.length - 1, p));
    scrollRef.current?.scrollTo({ x: clamped * width, animated: true });
    setPage(clamped);
    Haptics.selectionAsync();
  };

  const onScroll = (e: NativeSyntheticEvent<NativeScrollEvent>) => {
    const p = Math.round(e.nativeEvent.contentOffset.x / width);
    if (p !== page) setPage(p);
  };

  const exit = () => {
    // Replay: back exits to profile; first-run: proceed into the app.
    if (isReplay) {
      router.back();
    } else {
      router.replace("/(tabs)/discover");
    }
  };

  const finish = async () => {
    if (finishing) return;
    // Replay mode never re-saves the timestamp.
    if (isReplay) {
      exit();
      return;
    }
    setFinishing(true);
    try {
      Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success);
      const updated = await updatePreferences({
        tutorial_completed_at: new Date().toISOString(),
      });
      setUser(updated);
      analytics.capture(EVENTS.TUTORIAL_COMPLETED, { replay: isReplay }, { user: updated, allowDuplicate: true });
    } catch {
      // Non-blocking: even if the timestamp fails to persist, don't trap the
      // user in the tutorial. The gate will simply re-check next launch.
    } finally {
      setFinishing(false);
      router.replace("/(tabs)/discover");
    }
  };

  const isLast = page === PAGES.length - 1;

  return (
    <View style={styles.root}>
      {/* Top bar: page dots + Skip on every page */}
      <View style={[styles.topBar, { paddingTop: insets.top + 8 }]}>
        <View style={styles.dots}>
          {PAGES.map((p, i) => (
            <View key={p.key} style={[styles.dot, i === page && styles.dotActive]} />
          ))}
        </View>
        <Pressable
          onPress={finish}
          hitSlop={12}
          accessibilityRole="button"
          accessibilityLabel="Skip tutorial"
          testID="tutorial-skip"
        >
          <Text style={styles.skip}>Skip</Text>
        </Pressable>
      </View>

      <ScrollView
        ref={scrollRef}
        horizontal
        pagingEnabled
        showsHorizontalScrollIndicator={false}
        onScroll={onScroll}
        scrollEventThrottle={16}
        style={{ flex: 1 }}
      >
        {PAGES.map((p) => (
          <ScrollView
            key={p.key}
            style={{ width }}
            contentContainerStyle={styles.pageContent}
            showsVerticalScrollIndicator={false}
          >
            <Text style={styles.eyebrow}>{p.eyebrow}</Text>
            <Text style={styles.h1}>{p.title}</Text>
            <Text style={styles.body}>{p.body}</Text>

            <View style={styles.rows}>
              {p.rows.map((r) => (
                <View
                  key={r.label}
                  style={styles.row}
                  accessible
                  accessibilityLabel={`${r.label}. ${r.detail}`}
                >
                  <View style={[styles.rowIcon, { backgroundColor: `${r.tint}22` }]}>
                    <Ionicons name={r.icon} size={22} color={r.tint} />
                  </View>
                  <View style={{ flex: 1 }}>
                    <Text style={styles.rowLabel}>{r.label}</Text>
                    <Text style={styles.rowDetail}>{r.detail}</Text>
                  </View>
                </View>
              ))}
            </View>
          </ScrollView>
        ))}
      </ScrollView>

      {/* Bottom nav: Back / Next / Get started */}
      <View style={[styles.bottomBar, { paddingBottom: insets.bottom + 16 }]}>
        <Pressable
          onPress={() => goTo(page - 1)}
          disabled={page === 0}
          style={[styles.backBtn, page === 0 && styles.backBtnHidden]}
          accessibilityRole="button"
          accessibilityLabel="Previous page"
        >
          <Ionicons name="arrow-back" size={18} color={Colors.textSecondary} />
          <Text style={styles.backText}>Back</Text>
        </Pressable>

        <Pressable
          onPress={isLast ? finish : () => goTo(page + 1)}
          disabled={finishing}
          style={[styles.nextBtn, finishing && styles.btnDisabled]}
          accessibilityRole="button"
          accessibilityLabel={isLast ? "Get started" : "Next page"}
          testID={isLast ? "tutorial-get-started" : "tutorial-next"}
        >
          {finishing ? (
            <ActivityIndicator color="#0B0500" />
          ) : (
            <Text style={styles.nextText}>{isLast ? "Get started" : "Next"}</Text>
          )}
        </Pressable>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: Colors.obsidian },
  topBar: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingHorizontal: 24,
    paddingBottom: 8,
  },
  dots: { flexDirection: "row", gap: 6 },
  dot: {
    width: 7,
    height: 7,
    borderRadius: 4,
    backgroundColor: Colors.surfaceLight,
  },
  dotActive: { backgroundColor: Colors.amber, width: 20 },
  skip: { fontFamily: "Inter_600SemiBold", fontSize: 15, color: Colors.textSecondary },
  pageContent: { paddingHorizontal: 28, paddingTop: 24, paddingBottom: 24 },
  eyebrow: {
    fontFamily: "Inter_600SemiBold",
    fontSize: 11,
    letterSpacing: 2,
    textTransform: "uppercase",
    color: Colors.amber,
  },
  h1: {
    fontFamily: "Inter_800ExtraBold",
    fontSize: 30,
    color: Colors.text,
    marginTop: 10,
    lineHeight: 34,
  },
  body: {
    fontFamily: "Inter_400Regular",
    fontSize: 15,
    color: Colors.textSecondary,
    marginTop: 12,
    lineHeight: 22,
  },
  rows: { marginTop: 28, gap: 12 },
  row: {
    flexDirection: "row",
    alignItems: "center",
    gap: 14,
    borderWidth: 1,
    borderColor: Colors.border,
    backgroundColor: "rgba(255,255,255,0.03)",
    borderRadius: 16,
    padding: 16,
  },
  rowIcon: {
    width: 44,
    height: 44,
    borderRadius: 12,
    alignItems: "center",
    justifyContent: "center",
  },
  rowLabel: { fontFamily: "Inter_700Bold", fontSize: 15, color: Colors.text },
  rowDetail: {
    fontFamily: "Inter_400Regular",
    fontSize: 13,
    color: Colors.textTertiary,
    marginTop: 3,
    lineHeight: 18,
  },
  bottomBar: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingHorizontal: 24,
    paddingTop: 12,
    borderTopWidth: 1,
    borderTopColor: Colors.border,
    backgroundColor: Colors.velvet,
  },
  backBtn: { flexDirection: "row", alignItems: "center", gap: 6, paddingVertical: 8 },
  backBtnHidden: { opacity: 0 },
  backText: { fontFamily: "Inter_500Medium", fontSize: 15, color: Colors.textSecondary },
  nextBtn: {
    backgroundColor: Colors.amber,
    paddingHorizontal: 32,
    paddingVertical: 15,
    borderRadius: 16,
    minWidth: 140,
    alignItems: "center",
    justifyContent: "center",
  },
  nextText: { fontFamily: "Inter_700Bold", fontSize: 16, color: "#0B0500" },
  btnDisabled: { opacity: 0.6 },
});
