import { Redirect, Stack } from "expo-router";
import { ActivityIndicator, StyleSheet, View } from "react-native";

import { Colors } from "@/constants/colors";
import { useAuth } from "@/context/AuthContext";

/**
 * Onboarding stack. Only reachable by authenticated users who have NOT yet
 * completed onboarding — completed users are bounced straight to the tabs so
 * they never see the flow again.
 */
export default function OnboardingLayout() {
  const { user, loading } = useAuth();

  if (loading) {
    return (
      <View style={styles.loading}>
        <ActivityIndicator color={Colors.amber} />
      </View>
    );
  }
  if (!user) return <Redirect href="/(auth)/login" />;
  if (user.onboarding_completed === true) return <Redirect href="/(tabs)/discover" />;

  return (
    <Stack
      screenOptions={{
        headerShown: false,
        contentStyle: { backgroundColor: Colors.obsidian },
        animation: "slide_from_right",
        gestureEnabled: false,
      }}
    >
      <Stack.Screen name="services" />
      <Stack.Screen name="genres" />
      <Stack.Screen name="preferences" />
      <Stack.Screen name="taste" />
    </Stack>
  );
}

const styles = StyleSheet.create({
  loading: {
    flex: 1,
    backgroundColor: Colors.obsidian,
    alignItems: "center",
    justifyContent: "center",
  },
});
