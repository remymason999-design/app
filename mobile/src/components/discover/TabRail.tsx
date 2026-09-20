/**
 * TabRail — For You / Movies / TV Shows tab pills, horizontally scrollable.
 */
import React from "react";
import { Pressable, ScrollView, StyleSheet, Text } from "react-native";

import { Colors } from "@/constants/colors";
import { DISCOVER_TABS, DiscoverTabId } from "@/lib/discover-api";

interface Props {
  active: DiscoverTabId;
  onChange: (tab: DiscoverTabId) => void;
}

function TabRailImpl({ active, onChange }: Props) {
  return (
    <ScrollView
      horizontal
      showsHorizontalScrollIndicator={false}
      contentContainerStyle={styles.row}
      testID="discover-tabs"
    >
      {DISCOVER_TABS.map((t) => {
        const isActive = active === t.id;
        return (
          <Pressable
            key={t.id}
            onPress={() => onChange(t.id)}
            testID={`tab-${t.id}`}
            accessibilityRole="tab"
            accessibilityLabel={t.label}
            accessibilityState={{ selected: isActive }}
            style={[styles.pill, isActive ? styles.pillActive : styles.pillInactive]}
          >
            <Text style={[styles.label, isActive ? styles.labelActive : styles.labelInactive]}>
              {t.label}
            </Text>
          </Pressable>
        );
      })}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  row: { gap: 6, paddingHorizontal: 4, alignItems: "center" },
  pill: {
    paddingHorizontal: 14,
    minHeight: 32,
    borderRadius: 999,
    borderWidth: 1,
    alignItems: "center",
    justifyContent: "center",
  },
  pillActive: { backgroundColor: Colors.amber, borderColor: "rgba(255,122,24,0.4)" },
  pillInactive: { backgroundColor: "rgba(255,255,255,0.03)", borderColor: Colors.border },
  label: { fontSize: 13 },
  labelActive: { fontFamily: "Inter_700Bold", color: Colors.obsidian },
  labelInactive: { fontFamily: "Inter_500Medium", color: Colors.textSecondary },
});

export const TabRail = React.memo(TabRailImpl);
