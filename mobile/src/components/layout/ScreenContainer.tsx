/**
 * ScreenContainer — the shared layout wrapper for the four main tab screens
 * (Discover / Watchlist / Friends / Savings).
 *
 * The tab navigator already renders a header (LogoTitle + ProfileButton in
 * (tabs)/_layout.tsx), so screens must NOT re-add `insets.top` — that produced
 * the huge gap under the header. Content starts a small, consistent distance
 * below the header instead, and safe-area correctness is preserved by the
 * navigator's own header.
 *
 * It also reserves bottom padding equal to the (taller) tab bar height so that
 * scrollable content never hides behind the bar / home indicator.
 *
 * Two variants:
 *   - <ScreenContainer>            → a plain View (for non-scrolling screens).
 *   - <ScreenContainer scroll ...> → a ScrollView with the same paddings.
 * A FlatList-based screen (Watchlist) can instead read the paddings via
 * `useScreenPadding()`.
 */
import React from "react";
import {
  RefreshControlProps,
  ScrollView,
  ScrollViewProps,
  StyleProp,
  StyleSheet,
  View,
  ViewStyle,
} from "react-native";
import { useBottomTabBarHeight } from "@react-navigation/bottom-tabs";

import { Colors } from "@/constants/colors";

/** Gap between the navigator header and the first line of screen content. */
export const SCREEN_TOP_GAP = 12;
/** Consistent horizontal padding across all tab screens. */
export const SCREEN_H_PADDING = 20;
/** Extra breathing room below the last item, on top of the tab-bar height. */
export const SCREEN_BOTTOM_EXTRA = 24;

/**
 * Hook that returns the paddings a tab screen should apply. Safe to call inside
 * a tab screen (the bottom-tab context is always present there).
 */
export function useScreenPadding() {
  const tabBarHeight = useBottomTabBarHeight();
  return {
    paddingTop: SCREEN_TOP_GAP,
    paddingHorizontal: SCREEN_H_PADDING,
    paddingBottom: tabBarHeight + SCREEN_BOTTOM_EXTRA,
  };
}

interface CommonProps {
  children: React.ReactNode;
  /** Override the default horizontal padding (e.g. Discover uses 12). */
  horizontalPadding?: number;
  style?: StyleProp<ViewStyle>;
  contentContainerStyle?: StyleProp<ViewStyle>;
  testID?: string;
}

interface ScreenContainerProps extends CommonProps {
  /** Render as a ScrollView instead of a plain View. */
  scroll?: boolean;
  refreshControl?: React.ReactElement<RefreshControlProps>;
  keyboardShouldPersistTaps?: "always" | "never" | "handled";
  showsVerticalScrollIndicator?: boolean;
  onScroll?: ScrollViewProps["onScroll"];
  onLayout?: ScrollViewProps["onLayout"];
  scrollEventThrottle?: number;
}

export function ScreenContainer({
  children,
  scroll,
  horizontalPadding = SCREEN_H_PADDING,
  style,
  contentContainerStyle,
  refreshControl,
  keyboardShouldPersistTaps,
  showsVerticalScrollIndicator,
  onScroll,
  onLayout,
  scrollEventThrottle,
  testID,
}: ScreenContainerProps) {
  const tabBarHeight = useBottomTabBarHeight();

  const padding: ViewStyle = {
    paddingTop: SCREEN_TOP_GAP,
    paddingHorizontal: horizontalPadding,
    paddingBottom: tabBarHeight + SCREEN_BOTTOM_EXTRA,
  };

  if (scroll) {
    return (
      <ScrollView
        style={[styles.root, style]}
        contentContainerStyle={[padding, contentContainerStyle]}
        refreshControl={refreshControl}
        keyboardShouldPersistTaps={keyboardShouldPersistTaps}
        showsVerticalScrollIndicator={showsVerticalScrollIndicator}
        testID={testID}
        onScroll={onScroll}
        onLayout={onLayout}
        scrollEventThrottle={scrollEventThrottle}
      >
        {children}
      </ScrollView>
    );
  }

  return (
    <View style={[styles.root, padding, style]} testID={testID}>
      {children}
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: Colors.obsidian },
});
