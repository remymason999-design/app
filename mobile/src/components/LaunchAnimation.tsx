/**
 * LaunchAnimation — in-app opening animation for the native app.
 *
 * Expo Go ignores the native app.json splash and shows its own loader, so we
 * replicate the web's LaunchAnimation.jsx as a JS overlay that plays once per
 * cold start. It chains seamlessly from the static splash in dev/standalone
 * builds (mounted right after SplashScreen.hideAsync) and still plays in Expo
 * Go.
 *
 * Sequence (~1.8s):
 *   1. dark #05070A full-screen overlay + orange radial glow fades in
 *   2. two rounded card shapes slide in from left/right and snap together
 *   3. a match-glow pulse when the cards meet
 *   4. the WatchSmart mark image scales + fades in
 *   5. the WATCHSMART wordmark (letterspaced) fades in
 *   6. the whole overlay fades out and unmounts (onDone)
 *
 * Uses only react-native Animated (no new deps). After it unmounts it is fully
 * removed from the tree, so it never blocks interaction.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import {
  Animated,
  Easing,
  Image,
  StyleSheet,
  Text,
  View,
  useWindowDimensions,
} from "react-native";

import { Colors } from "@/constants/colors";

interface Props {
  onDone?: () => void;
}

const CARD_W = 128;
const CARD_H = 180;

export function LaunchAnimation({ onDone }: Props) {
  const { width } = useWindowDimensions();
  const [gone, setGone] = useState(false);

  // Animated values (created once).
  const overlay = useRef(new Animated.Value(1)).current;
  const glow = useRef(new Animated.Value(0)).current;
  const leftX = useRef(new Animated.Value(-(width / 2 + CARD_W))).current;
  const rightX = useRef(new Animated.Value(width / 2 + CARD_W)).current;
  const cardsOpacity = useRef(new Animated.Value(0)).current;
  const cardsFade = useRef(new Animated.Value(1)).current;
  const snap = useRef(new Animated.Value(0)).current;
  const mark = useRef(new Animated.Value(0)).current;
  const wordmark = useRef(new Animated.Value(0)).current;

  useEffect(() => {
    const seq = Animated.sequence([
      // 1. glow + cards slide in and meet
      Animated.parallel([
        Animated.timing(glow, {
          toValue: 1,
          duration: 500,
          easing: Easing.out(Easing.quad),
          useNativeDriver: true,
        }),
        Animated.timing(cardsOpacity, {
          toValue: 1,
          duration: 300,
          useNativeDriver: true,
        }),
        Animated.timing(leftX, {
          toValue: -CARD_W * 0.32,
          duration: 620,
          easing: Easing.out(Easing.cubic),
          useNativeDriver: true,
        }),
        Animated.timing(rightX, {
          toValue: CARD_W * 0.32,
          duration: 620,
          easing: Easing.out(Easing.cubic),
          useNativeDriver: true,
        }),
      ]),
      // 2. snap pulse
      Animated.timing(snap, {
        toValue: 1,
        duration: 340,
        easing: Easing.out(Easing.quad),
        useNativeDriver: true,
      }),
      // 3. cards recede as the mark forms
      Animated.parallel([
        Animated.timing(cardsFade, {
          toValue: 0.12,
          duration: 320,
          useNativeDriver: true,
        }),
        Animated.spring(mark, {
          toValue: 1,
          friction: 6,
          tension: 90,
          useNativeDriver: true,
        }),
      ]),
      // 4. wordmark
      Animated.timing(wordmark, {
        toValue: 1,
        duration: 340,
        easing: Easing.out(Easing.quad),
        useNativeDriver: true,
      }),
      // 5. hold, then fade the whole overlay out
      Animated.delay(360),
      Animated.timing(overlay, {
        toValue: 0,
        duration: 320,
        easing: Easing.inOut(Easing.quad),
        useNativeDriver: true,
      }),
    ]);

    seq.start(({ finished }) => {
      if (finished) {
        setGone(true);
        onDone?.();
      }
    });

    return () => seq.stop();
    // Run exactly once on mount.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const glowScale = useMemo(
    () => glow.interpolate({ inputRange: [0, 1], outputRange: [0.85, 1.05] }),
    [glow]
  );
  const glowOpacity = useMemo(
    () => glow.interpolate({ inputRange: [0, 1], outputRange: [0, 0.55] }),
    [glow]
  );
  const snapScale = snap.interpolate({ inputRange: [0, 1], outputRange: [0.4, 1.8] });
  const snapOpacity = snap.interpolate({
    inputRange: [0, 0.4, 1],
    outputRange: [0, 0.8, 0],
  });
  const markScale = mark.interpolate({ inputRange: [0, 1], outputRange: [0.82, 1] });

  if (gone) return null;

  return (
    <Animated.View
      style={[styles.overlay, { opacity: overlay }]}
      pointerEvents="auto"
      accessibilityElementsHidden
      importantForAccessibility="no-hide-descendants"
    >
      {/* Centre orange radial glow */}
      <Animated.View
        style={[
          styles.glow,
          { opacity: glowOpacity, transform: [{ scale: glowScale }] },
        ]}
      />

      {/* Two card backs sliding in and meeting */}
      <Animated.View
        style={[
          styles.card,
          {
            opacity: Animated.multiply(cardsOpacity, cardsFade),
            transform: [{ translateX: leftX }, { rotate: "-6deg" }],
          },
        ]}
      />
      <Animated.View
        style={[
          styles.card,
          {
            opacity: Animated.multiply(cardsOpacity, cardsFade),
            transform: [{ translateX: rightX }, { rotate: "6deg" }],
          },
        ]}
      />

      {/* Snap / match glow pulse */}
      <Animated.View
        style={[
          styles.snap,
          { opacity: snapOpacity, transform: [{ scale: snapScale }] },
        ]}
      />

      {/* Hero mark */}
      <Animated.View
        style={[styles.markWrap, { opacity: mark, transform: [{ scale: markScale }] }]}
      >
        <Image
          source={require("../../assets/images/watchsmart-mark.png")}
          style={styles.mark}
          resizeMode="contain"
        />
      </Animated.View>

      {/* Wordmark */}
      <Animated.View style={[styles.wordmarkWrap, { opacity: wordmark }]}>
        <Text style={styles.wordmark}>
          <Text style={styles.wordmarkWhite}>WATCH</Text>
          <Text style={styles.wordmarkAmber}>SMART</Text>
        </Text>
      </Animated.View>
    </Animated.View>
  );
}

const styles = StyleSheet.create({
  overlay: {
    ...StyleSheet.absoluteFillObject,
    backgroundColor: Colors.obsidian,
    alignItems: "center",
    justifyContent: "center",
    zIndex: 1000,
  },
  glow: {
    position: "absolute",
    width: 420,
    height: 420,
    borderRadius: 210,
    backgroundColor: "rgba(255,122,24,0.28)",
  },
  card: {
    position: "absolute",
    width: CARD_W,
    height: CARD_H,
    borderRadius: 20,
    backgroundColor: Colors.velvet,
    borderWidth: 1,
    borderColor: "rgba(255,255,255,0.10)",
  },
  snap: {
    position: "absolute",
    width: 180,
    height: 180,
    borderRadius: 90,
    backgroundColor: "rgba(255,140,40,0.5)",
  },
  markWrap: {
    position: "absolute",
    alignItems: "center",
    justifyContent: "center",
  },
  mark: { width: 104, height: 104 },
  wordmarkWrap: {
    position: "absolute",
    bottom: "38%",
    alignItems: "center",
  },
  wordmark: {
    fontFamily: "Inter_800ExtraBold",
    fontSize: 26,
    letterSpacing: 4,
  },
  wordmarkWhite: { color: Colors.text },
  wordmarkAmber: { color: Colors.amber },
});
