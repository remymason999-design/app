import { Redirect } from "expo-router";
import { ActivityIndicator, Image, StyleSheet, View } from "react-native";

import { Colors } from "@/constants/colors";
import { useAuth } from "@/context/AuthContext";

/**
 * Branded gate screen: shows the WatchSmart mark while the stored session is
 * being restored, then routes to the app or the login flow.
 */
export default function Index() {
  const { user, loading } = useAuth();

  if (loading) {
    return (
      <View style={styles.splash}>
        <Image
          source={require("../../assets/images/watchsmart-mark.png")}
          style={styles.mark}
          resizeMode="contain"
        />
        <ActivityIndicator color={Colors.amber} style={{ marginTop: 24 }} />
      </View>
    );
  }

  if (!user) return <Redirect href="/(auth)/login" />;
  if (user.onboarding_completed !== true) return <Redirect href="/onboarding/services" />;
  return <Redirect href="/(tabs)/discover" />;
}

const styles = StyleSheet.create({
  splash: {
    flex: 1,
    backgroundColor: Colors.obsidian,
    alignItems: "center",
    justifyContent: "center",
  },
  mark: { width: 140, height: 140 },
});
