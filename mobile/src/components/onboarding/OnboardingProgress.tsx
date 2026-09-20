import { StyleSheet, View } from "react-native";

import { Colors } from "@/constants/colors";

/**
 * Segmented progress bar for the onboarding flow
 * (Services → Genres → Preferences → Taste).
 */
export function OnboardingProgress({
  step,
  total = 4,
}: {
  step: number;
  total?: number;
}) {
  const segs = Array.from({ length: total }, (_, i) => i + 1);
  return (
    <View style={styles.row} accessibilityLabel={`Step ${step} of ${total}`}>
      {segs.map((s) => (
        <View key={s} style={[styles.seg, s <= step ? styles.on : styles.off]} />
      ))}
    </View>
  );
}

const styles = StyleSheet.create({
  row: { flexDirection: "row", gap: 6, marginBottom: 4 },
  seg: { flex: 1, height: 4, borderRadius: 2 },
  on: { backgroundColor: Colors.amber },
  off: { backgroundColor: "rgba(255,255,255,0.10)" },
});
