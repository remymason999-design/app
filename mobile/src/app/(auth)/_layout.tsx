import { Redirect, Stack } from "expo-router";
import { ActivityIndicator, View } from "react-native";

import { Colors } from "@/constants/colors";
import { useAuth } from "@/context/AuthContext";

export default function AuthLayout() {
  const { user, loading } = useAuth();

  if (loading) {
    return (
      <View
        style={{
          flex: 1,
          backgroundColor: Colors.obsidian,
          alignItems: "center",
          justifyContent: "center",
        }}
      >
        <ActivityIndicator color={Colors.amber} />
      </View>
    );
  }
  if (user) return <Redirect href="/(tabs)/discover" />;

  return (
    <Stack
      screenOptions={{
        headerShown: false,
        contentStyle: { backgroundColor: Colors.obsidian },
        animation: "slide_from_right",
      }}
    />
  );
}
