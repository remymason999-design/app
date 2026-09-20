import * as Haptics from "expo-haptics";
import * as AppleAuthentication from "expo-apple-authentication";
import { router } from "expo-router";
import { useEffect, useState } from "react";
import {
  ActivityIndicator,
  Image,
  Pressable,
  StyleSheet,
  Text,
  TextInput,
  View,
  Platform,
} from "react-native";
import { KeyboardAwareScrollView } from "react-native-keyboard-controller";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { Colors } from "@/constants/colors";
import { useAuth } from "@/context/AuthContext";
import { AppleLoginPayload, getFriendlyMessage } from "@/lib/api";

export default function Login() {
  const { login, loginWithApple, loginAndLinkApple } = useAuth();
  const insets = useSafeAreaInsets();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [appleAvailable, setAppleAvailable] = useState(false);
  const [pendingAppleLink, setPendingAppleLink] = useState<AppleLoginPayload | null>(null);

  useEffect(() => {
    if (Platform.OS !== "ios") return;
    AppleAuthentication.isAvailableAsync().then(setAppleAvailable).catch(() => {
      setAppleAvailable(false);
    });
  }, []);

  const canSubmit = email.trim().length > 3 && password.length >= 6 && !busy;

  const submit = async () => {
    if (!canSubmit) return;
    setBusy(true);
    setError(null);
    try {
      const u = pendingAppleLink
        ? await loginAndLinkApple(email.trim(), password, pendingAppleLink)
        : await login(email.trim(), password);
      setPendingAppleLink(null);
      Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success);
      router.replace(u.onboarding_completed === true ? "/(tabs)/discover" : "/onboarding/services");
    } catch (e) {
      Haptics.notificationAsync(Haptics.NotificationFeedbackType.Error);
      if (pendingAppleLink) {
        setPendingAppleLink(null);
        setError("Apple could not be linked. Sign in normally or try Apple again.");
      } else {
        setError(getFriendlyMessage(e));
      }
    } finally {
      setBusy(false);
    }
  };

  const submitApple = async () => {
    if (busy) return;
    setBusy(true);
    setError(null);
    let applePayload: AppleLoginPayload | null = null;
    try {
      const credential = await AppleAuthentication.signInAsync({
        requestedScopes: [
          AppleAuthentication.AppleAuthenticationScope.FULL_NAME,
          AppleAuthentication.AppleAuthenticationScope.EMAIL,
        ],
      });
      if (!credential.identityToken) {
        setError("Apple did not return a valid sign-in credential. Please try again.");
        return;
      }
      const fullName = [credential.fullName?.givenName, credential.fullName?.familyName]
        .filter(Boolean)
        .join(" ");
      applePayload = {
        identity_token: credential.identityToken,
        authorization_code: credential.authorizationCode,
        apple_user: credential.user,
        full_name: fullName || null,
        email: credential.email,
      };
      const u = await loginWithApple(applePayload);
      Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success);
      router.replace(u.onboarding_completed === true ? "/(tabs)/discover" : "/onboarding/services");
    } catch (e) {
      const code = (e as { code?: string })?.code;
      if (code !== "ERR_REQUEST_CANCELED") {
        const status = (e as { response?: { status?: number } })?.response?.status;
        const detail = (e as { response?: { data?: { detail?: unknown } } })?.response?.data
          ?.detail;
        const needsLink =
          status === 409 &&
          typeof detail === "string" &&
          detail.includes("already uses this email");
        if (needsLink && applePayload) {
          setPendingAppleLink(applePayload);
          if (applePayload.email) setEmail(applePayload.email);
          setError("Sign in with your existing WatchSmart password to securely link Apple.");
        } else {
          Haptics.notificationAsync(Haptics.NotificationFeedbackType.Error);
          setError(getFriendlyMessage(e));
        }
      }
    } finally {
      setBusy(false);
    }
  };

  return (
    <KeyboardAwareScrollView
      style={{ flex: 1, backgroundColor: Colors.obsidian }}
      contentContainerStyle={[
        styles.container,
        { paddingTop: insets.top + 48, paddingBottom: insets.bottom + 24 },
      ]}
      keyboardShouldPersistTaps="handled"
      bottomOffset={24}
    >
      <Image
        source={require("../../../assets/images/watchsmart-mark.png")}
        style={styles.mark}
        resizeMode="contain"
        accessibilityLabel="WatchSmart logo"
      />
      <Text style={styles.title}>Welcome back</Text>
      <Text style={styles.subtitle}>Sign in to keep discovering what to watch.</Text>

      <View style={styles.form}>
        <Text style={styles.label}>Email</Text>
        <TextInput
          style={styles.input}
          value={email}
          onChangeText={setEmail}
          placeholder="you@example.com"
          placeholderTextColor={Colors.textTertiary}
          keyboardType="email-address"
          autoCapitalize="none"
          autoComplete="email"
          textContentType="emailAddress"
          accessibilityLabel="Email address"
          testID="login-email"
        />
        <Text style={styles.label}>Password</Text>
        <TextInput
          style={styles.input}
          value={password}
          onChangeText={setPassword}
          placeholder="Your password"
          placeholderTextColor={Colors.textTertiary}
          secureTextEntry
          autoComplete="password"
          textContentType="password"
          accessibilityLabel="Password"
          testID="login-password"
          onSubmitEditing={submit}
        />
        {pendingAppleLink ? (
          <Pressable
            onPress={() => {
              setPendingAppleLink(null);
              setError(null);
            }}
            accessibilityRole="button"
            accessibilityLabel="Cancel Apple account linking"
            style={styles.cancelLink}
          >
            <Text style={styles.cancelLinkText}>Cancel Apple linking</Text>
          </Pressable>
        ) : null}

        {error ? (
          <Text style={styles.error} accessibilityLiveRegion="polite">
            {error}
          </Text>
        ) : null}

        <Pressable
          style={({ pressed }) => [
            styles.primaryBtn,
            !canSubmit && styles.btnDisabled,
            pressed && canSubmit && styles.btnPressed,
          ]}
          onPress={submit}
          disabled={!canSubmit}
          accessibilityRole="button"
          accessibilityLabel="Sign in"
          testID="login-submit"
        >
          {busy ? (
            <ActivityIndicator color="#fff" />
          ) : (
            <Text style={styles.primaryBtnText}>Sign In</Text>
          )}
        </Pressable>

        {appleAvailable ? (
          <>
            <View style={styles.separator} accessibilityElementsHidden>
              <View style={styles.separatorLine} />
              <Text style={styles.separatorText}>OR</Text>
              <View style={styles.separatorLine} />
            </View>
            <AppleAuthentication.AppleAuthenticationButton
              buttonType={AppleAuthentication.AppleAuthenticationButtonType.SIGN_IN}
              buttonStyle={AppleAuthentication.AppleAuthenticationButtonStyle.WHITE}
              cornerRadius={16}
              style={styles.appleButton}
              onPress={submitApple}
              testID="login-apple"
            />
          </>
        ) : null}
      </View>

      <Pressable
        onPress={() => router.push("/(auth)/register")}
        style={styles.linkRow}
        accessibilityRole="button"
        accessibilityLabel="Create an account"
        testID="goto-register"
      >
        <Text style={styles.linkMuted}>New to WatchSmart? </Text>
        <Text style={styles.link}>Create an account</Text>
      </Pressable>
    </KeyboardAwareScrollView>
  );
}

const styles = StyleSheet.create({
  container: { paddingHorizontal: 28, alignItems: "center" },
  mark: { width: 96, height: 96, marginBottom: 20 },
  title: {
    fontFamily: "Inter_800ExtraBold",
    fontSize: 28,
    color: Colors.text,
    marginBottom: 6,
  },
  subtitle: {
    fontFamily: "Inter_400Regular",
    fontSize: 15,
    color: Colors.textSecondary,
    marginBottom: 32,
    textAlign: "center",
  },
  form: { width: "100%", maxWidth: 420 },
  label: {
    fontFamily: "Inter_600SemiBold",
    fontSize: 13,
    color: Colors.textSecondary,
    marginBottom: 6,
    marginTop: 14,
  },
  input: {
    backgroundColor: Colors.velvet,
    borderColor: Colors.border,
    borderWidth: 1,
    borderRadius: 14,
    paddingHorizontal: 16,
    paddingVertical: 14,
    fontFamily: "Inter_500Medium",
    fontSize: 16,
    color: Colors.text,
    minHeight: 52,
  },
  error: {
    fontFamily: "Inter_500Medium",
    color: Colors.danger,
    fontSize: 14,
    marginTop: 14,
    textAlign: "center",
  },
  cancelLink: { alignSelf: "flex-end", paddingVertical: 10 },
  cancelLinkText: {
    fontFamily: "Inter_600SemiBold",
    color: Colors.textSecondary,
    fontSize: 13,
  },
  primaryBtn: {
    backgroundColor: Colors.amber,
    borderRadius: 16,
    minHeight: 54,
    alignItems: "center",
    justifyContent: "center",
    marginTop: 24,
  },
  btnPressed: { opacity: 0.85 },
  btnDisabled: { opacity: 0.45 },
  primaryBtnText: {
    fontFamily: "Inter_700Bold",
    fontSize: 17,
    color: "#0B0500",
  },
  separator: {
    flexDirection: "row",
    alignItems: "center",
    gap: 12,
    marginVertical: 22,
  },
  separatorLine: { flex: 1, height: 1, backgroundColor: Colors.border },
  separatorText: {
    fontFamily: "Inter_600SemiBold",
    color: Colors.textTertiary,
    fontSize: 12,
  },
  appleButton: { width: "100%", height: 54 },
  linkRow: { flexDirection: "row", marginTop: 28, minHeight: 44, alignItems: "center" },
  linkMuted: { fontFamily: "Inter_400Regular", color: Colors.textSecondary, fontSize: 15 },
  link: { fontFamily: "Inter_700Bold", color: Colors.amber, fontSize: 15 },
});
