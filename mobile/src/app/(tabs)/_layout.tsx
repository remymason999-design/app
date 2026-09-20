import { Ionicons } from "@expo/vector-icons";
import { Redirect, Tabs, router } from "expo-router";
import { useEffect, useState } from "react";
import {
  ActivityIndicator,
  Image,
  Pressable,
  StyleSheet,
  Text,
  View,
} from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { Colors } from "@/constants/colors";
import { useAuth } from "@/context/AuthContext";
import { resolveImageUrl } from "@/lib/api";

function ProfileButton() {
  const { user } = useAuth();
  const initial = (String(user?.name || user?.email || "?").trim()[0] || "?").toUpperCase();
  const picture = resolveImageUrl(typeof user?.picture === "string" ? user.picture : null);
  const [imgError, setImgError] = useState(false);
  useEffect(() => setImgError(false), [picture]);
  const showImage = !!picture && !imgError;
  return (
    <Pressable
      onPress={() => router.push("/profile")}
      style={({ pressed }) => [styles.avatar, pressed && { opacity: 0.8 }]}
      accessibilityRole="button"
      accessibilityLabel="Open profile"
      testID="profile-avatar"
      hitSlop={8}
    >
      {showImage ? (
        <Image
          source={{ uri: picture }}
          style={styles.avatarImg}
          onError={() => setImgError(true)}
        />
      ) : (
        <Text style={styles.avatarText}>{initial}</Text>
      )}
    </Pressable>
  );
}

function LogoTitle() {
  return (
    <View style={styles.logoRow} accessibilityLabel="WatchSmart">
      <Image
        source={require("../../../assets/images/watchsmart-mark.png")}
        style={{ width: 34, height: 28 }}
        resizeMode="contain"
      />
      <Text style={styles.logoText}>
        Watch<Text style={{ color: Colors.amber }}>Smart</Text>
      </Text>
    </View>
  );
}

export default function TabsLayout() {
  const { user, loading } = useAuth();
  const insets = useSafeAreaInsets();

  if (loading) {
    return (
      <View style={styles.loading}>
        <ActivityIndicator color={Colors.amber} />
      </View>
    );
  }
  if (!user) return <Redirect href="/(auth)/login" />;
  if (user.onboarding_completed !== true) return <Redirect href="/onboarding/services" />;

  const rawUnseen = user.watchlist_unseen ?? 0;
  // Premium bar: ~64pt of content sitting above the home indicator, with the
  // background extending fully to the screen bottom (behind the indicator).
  const BAR_CONTENT = 64;
  const ICON_SIZE = 26;

  return (
    <Tabs
      screenOptions={{
        headerStyle: { backgroundColor: Colors.obsidian },
        headerShadowVisible: false,
        headerTitleAlign: "left",
        headerTitle: () => <LogoTitle />,
        headerRight: () => (
          <View style={{ marginRight: 16 }}>
            <ProfileButton />
          </View>
        ),
        tabBarStyle: {
          backgroundColor: Colors.velvet,
          borderTopColor: Colors.border,
          borderTopWidth: StyleSheet.hairlineWidth,
          // Background fills to the very bottom of the screen; content sits
          // above the home indicator via the padding below.
          height: BAR_CONTENT + insets.bottom,
          paddingBottom: insets.bottom,
          paddingTop: 8,
          // Subtle elevation over the dark background.
          elevation: 12,
          shadowColor: "#000",
          shadowOpacity: 0.35,
          shadowRadius: 12,
          shadowOffset: { width: 0, height: -4 },
        },
        tabBarItemStyle: {
          minHeight: 44,
          paddingVertical: 4,
        },
        tabBarActiveTintColor: Colors.amber,
        tabBarInactiveTintColor: Colors.textTertiary,
        tabBarLabelStyle: {
          fontFamily: "Inter_600SemiBold",
          fontSize: 11,
          marginTop: 2,
        },
      }}
    >
      <Tabs.Screen
        name="discover"
        options={{
          title: "Discover",
          tabBarIcon: ({ color }) => <Ionicons name="home" size={ICON_SIZE} color={color} />,
        }}
      />
      <Tabs.Screen
        name="watchlist"
        options={{
          title: "Library",
          headerShown: false,
          tabBarBadge: rawUnseen > 0 ? (rawUnseen > 99 ? "99+" : rawUnseen) : undefined,
          tabBarBadgeStyle: {
            backgroundColor: Colors.amber,
            color: "#0B0500",
            fontFamily: "Inter_700Bold",
            fontSize: 10,
            minWidth: 18,
            height: 18,
            lineHeight: 14,
            borderRadius: 9,
            // Keep the badge tucked to the icon's top-right, not over it.
            marginLeft: 2,
          },
          tabBarIcon: ({ color }) => <Ionicons name="bookmark" size={ICON_SIZE} color={color} />,
        }}
      />
      <Tabs.Screen
        name="friends"
        options={{
          title: "Friends",
          tabBarIcon: ({ color }) => <Ionicons name="people" size={ICON_SIZE} color={color} />,
        }}
      />
      <Tabs.Screen
        name="savings"
        options={{
          title: "Savings",
          tabBarIcon: ({ color }) => <Ionicons name="pricetag" size={ICON_SIZE} color={color} />,
        }}
      />
    </Tabs>
  );
}

const styles = StyleSheet.create({
  loading: {
    flex: 1,
    backgroundColor: Colors.obsidian,
    alignItems: "center",
    justifyContent: "center",
  },
  logoRow: { flexDirection: "row", alignItems: "center", gap: 8 },
  logoText: { fontFamily: "Inter_800ExtraBold", fontSize: 19, color: Colors.text },
  avatar: {
    width: 36,
    height: 36,
    borderRadius: 18,
    backgroundColor: Colors.amber,
    alignItems: "center",
    justifyContent: "center",
  },
  avatarText: { fontFamily: "Inter_800ExtraBold", fontSize: 16, color: "#0B0500" },
  avatarImg: { width: 36, height: 36, borderRadius: 18 },
});
