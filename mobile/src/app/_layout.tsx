import {
  Inter_400Regular,
  Inter_500Medium,
  Inter_600SemiBold,
  Inter_700Bold,
  Inter_800ExtraBold,
  useFonts,
} from "@expo-google-fonts/inter";
import { QueryClientProvider } from "@tanstack/react-query";
import { Stack, usePathname } from "expo-router";
import * as SplashScreen from "expo-splash-screen";
import { StatusBar } from "expo-status-bar";
import { useEffect, useState } from "react";
import { GestureHandlerRootView } from "react-native-gesture-handler";
import { KeyboardProvider } from "react-native-keyboard-controller";
import { SafeAreaProvider } from "react-native-safe-area-context";

import { LaunchAnimation } from "@/components/LaunchAnimation";
import { PushNotificationsBridge } from "@/components/PushNotificationsBridge";
import { Colors } from "@/constants/colors";
import { AuthProvider } from "@/context/AuthContext";
import { queryClient } from "@/lib/query-client";
import { analytics } from "@/lib/analytics";

SplashScreen.preventAutoHideAsync();

/**
 * Module-level flag so the launch animation plays exactly once per cold start.
 * It survives Fast Refresh / re-renders (module state persists) but resets on a
 * real app relaunch — so it never re-plays during navigation. Intentionally NOT
 * persisted to storage.
 */
let launchAnimationShown = false;

// Dev-only: the Expo web preview can skip the launch animation (screenshot /
// layout-verification tooling passes ?dev_token=… and needs the real screen
// immediately). No-op on native and in production builds.
if (__DEV__ && typeof window !== "undefined" && window.location?.search?.includes("dev_token=")) {
  launchAnimationShown = true;
}

export default function RootLayout() {
  const pathname = usePathname();
  const previousPath = useState<string | null>(null);
  useEffect(() => {
    analytics.init();
    analytics.appOpened();
  }, []);
  useEffect(() => {
    if (!pathname || previousPath[0] === pathname) return;
    analytics.capture(analytics.EVENTS.SCREEN_VIEWED, {
      screen_name: pathname,
      ...(previousPath[0] ? { previous_screen: previousPath[0] } : {}),
      source: "navigation",
    }, { dedupeKey: `screen:${pathname}` });
    previousPath[1](pathname);
  }, [pathname, previousPath]);
  const [fontsLoaded, fontError] = useFonts({
    Inter_400Regular,
    Inter_500Medium,
    Inter_600SemiBold,
    Inter_700Bold,
    Inter_800ExtraBold,
  });

  // Show the in-app launch animation once per cold start, chained right after
  // the static splash is hidden.
  const [showLaunch, setShowLaunch] = useState(!launchAnimationShown);

  useEffect(() => {
    if (fontsLoaded || fontError) {
      SplashScreen.hideAsync();
      if (!launchAnimationShown) {
        launchAnimationShown = true;
      }
    }
  }, [fontsLoaded, fontError]);

  if (!fontsLoaded && !fontError) return null;

  return (
    <GestureHandlerRootView style={{ flex: 1, backgroundColor: Colors.obsidian }}>
      <SafeAreaProvider>
        <KeyboardProvider>
          <QueryClientProvider client={queryClient}>
            <AuthProvider>
              <PushNotificationsBridge />
              <StatusBar style="light" />
              <Stack
                screenOptions={{
                  headerShown: false,
                  contentStyle: { backgroundColor: Colors.obsidian },
                  animation: "slide_from_right",
                }}
              >
                <Stack.Screen name="index" />
                <Stack.Screen name="(auth)" options={{ animation: "fade" }} />
                <Stack.Screen name="onboarding" options={{ animation: "fade" }} />
                <Stack.Screen name="(tabs)" options={{ animation: "fade" }} />
                <Stack.Screen
                  name="profile"
                  options={{ presentation: "modal", animation: "slide_from_bottom" }}
                />
                <Stack.Screen
                  name="plus"
                  options={{ presentation: "modal", animation: "slide_from_right" }}
                />
                <Stack.Screen
                  name="tutorial"
                  options={{ presentation: "modal", animation: "slide_from_bottom" }}
                />
              </Stack>
            </AuthProvider>
          </QueryClientProvider>
        </KeyboardProvider>
      </SafeAreaProvider>
      {showLaunch ? (
        <LaunchAnimation onDone={() => setShowLaunch(false)} />
      ) : null}
    </GestureHandlerRootView>
  );
}
