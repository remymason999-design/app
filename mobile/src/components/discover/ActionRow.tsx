/**
 * ActionRow — the swipe action buttons below the card deck.
 * Mirrors the web app: Rewind (small) / Skip / Watched (emerald) / Save (amber).
 * Buttons trigger the same actions as the pan gesture and are disabled while an
 * action animation is in flight (no double-submit).
 */
import { Ionicons } from "@expo/vector-icons";
import React from "react";
import { Pressable, StyleSheet, Text, View } from "react-native";

import { Colors } from "@/constants/colors";

interface Props {
  onRewind: () => void;
  onSkip: () => void;
  onWatched: () => void;
  onSave: () => void;
  canRewind: boolean;
  busy: boolean;
}

interface BtnProps {
  icon: keyof typeof Ionicons.glyphMap;
  label: string;
  onPress: () => void;
  color: string;
  borderColor: string;
  bg: string;
  disabled: boolean;
  small?: boolean;
  testID: string;
}

function ActionBtn({
  icon,
  label,
  onPress,
  color,
  borderColor,
  bg,
  disabled,
  small,
  testID,
}: BtnProps) {
  const size = small ? 44 : 56;
  const iconSize = small ? 20 : 24;
  return (
    <View style={[styles.btnCol, disabled && styles.disabled]}>
      <Pressable
        onPress={onPress}
        disabled={disabled}
        testID={testID}
        accessibilityRole="button"
        accessibilityLabel={label}
        accessibilityState={{ disabled }}
        hitSlop={6}
        style={({ pressed }) => [
          styles.btn,
          {
            width: size,
            height: size,
            borderRadius: size / 2,
            borderColor,
            backgroundColor: bg,
          },
          pressed && !disabled && { transform: [{ scale: 0.94 }] },
        ]}
      >
        <Ionicons name={icon} size={iconSize} color={color} />
      </Pressable>
      <Text style={[styles.label, { color }]}>{label}</Text>
    </View>
  );
}

function ActionRowImpl({ onRewind, onSkip, onWatched, onSave, canRewind, busy }: Props) {
  return (
    <View style={styles.row} testID="action-buttons">
      <ActionBtn
        icon="arrow-undo"
        label="Rewind"
        onPress={onRewind}
        disabled={!canRewind || busy}
        color="#E5E7EB"
        borderColor="rgba(255,255,255,0.25)"
        bg="#141B26"
        small
        testID="btn-rewind"
      />
      <ActionBtn
        icon="close"
        label="Skip"
        onPress={onSkip}
        disabled={busy}
        color="#E5E7EB"
        borderColor="rgba(255,255,255,0.15)"
        bg="#1A2230"
        testID="btn-skip"
      />
      <ActionBtn
        icon="eye"
        label="Watched"
        onPress={onWatched}
        disabled={busy}
        color={Colors.success}
        borderColor="rgba(34,197,94,0.5)"
        bg="#0E141C"
        testID="btn-watched"
      />
      <ActionBtn
        icon="heart"
        label="Save"
        onPress={onSave}
        disabled={busy}
        color={Colors.amber}
        borderColor="rgba(255,122,24,0.5)"
        bg="#0E141C"
        testID="btn-save"
      />
    </View>
  );
}

const styles = StyleSheet.create({
  row: {
    flexDirection: "row",
    alignItems: "flex-start",
    justifyContent: "center",
    gap: 20,
    paddingHorizontal: 16,
    paddingTop: 10,
  },
  btnCol: { alignItems: "center", gap: 4 },
  disabled: { opacity: 0.4 },
  btn: {
    borderWidth: 2,
    alignItems: "center",
    justifyContent: "center",
  },
  label: {
    fontFamily: "Inter_600SemiBold",
    fontSize: 10,
    letterSpacing: 1,
    textTransform: "uppercase",
  },
});

export const ActionRow = React.memo(ActionRowImpl);
