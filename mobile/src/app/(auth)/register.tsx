import * as Haptics from "expo-haptics";
import { router } from "expo-router";
import { useState } from "react";
import {
  ActivityIndicator,
  Image,
  Pressable,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";
import { KeyboardAwareScrollView } from "react-native-keyboard-controller";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { Colors } from "@/constants/colors";
import { useAuth } from "@/context/AuthContext";
import { getFriendlyMessage } from "@/lib/api";
import { updatePreferences } from "@/lib/onboarding-api";

/**
 * Validate a DD/MM/YYYY string and convert it to an ISO "YYYY-MM-DD" date.
 * Returns null when the string is empty (DOB is optional) and throws-free —
 * callers distinguish "empty" (null) from "invalid" via `dobError`.
 */
function parseDob(input: string): { iso: string | null; error: string | null } {
  const t = input.trim();
  if (t === "") return { iso: null, error: null };
  const m = t.match(/^(\d{2})\/(\d{2})\/(\d{4})$/);
  if (!m) return { iso: null, error: "Use DD/MM/YYYY." };
  const day = Number(m[1]);
  const month = Number(m[2]);
  const year = Number(m[3]);
  if (month < 1 || month > 12) return { iso: null, error: "Enter a valid month." };
  const daysInMonth = new Date(year, month, 0).getDate();
  if (day < 1 || day > daysInMonth) return { iso: null, error: "Enter a valid day." };
  const today = new Date();
  const entered = new Date(year, month - 1, day);
  if (year < 1900 || entered > today) return { iso: null, error: "Enter a valid date of birth." };
  const iso = `${year}-${String(month).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
  return { iso, error: null };
}

function formatDobInput(input: string): string {
  const digits = input.replace(/\D/g, "").slice(0, 8);
  if (digits.length <= 2) return digits;
  if (digits.length <= 4) return `${digits.slice(0, 2)}/${digits.slice(2)}`;
  return `${digits.slice(0, 2)}/${digits.slice(2, 4)}/${digits.slice(4)}`;
}

export default function Register() {
  const { register } = useAuth();
  const insets = useSafeAreaInsets();
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [dob, setDob] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const dobParsed = parseDob(dob);
  const dobError = dob.trim() !== "" ? dobParsed.error : null;

  const canSubmit =
    name.trim().length >= 1 &&
    email.trim().length > 3 &&
    password.length >= 8 &&
    !dobError &&
    !busy;

  const submit = async () => {
    if (!canSubmit) return;
    setBusy(true);
    setError(null);
    try {
      const u = await register(name.trim(), email.trim(), password);
      // Date of birth is optional. The shared register() only carries the core
      // fields, so persist DOB via the preferences endpoint right after signup.
      if (dobParsed.iso) {
        try {
          await updatePreferences({ dob: dobParsed.iso });
        } catch {
          // Non-fatal — the account is created; DOB can be set later in profile.
        }
      }
      Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success);
      router.replace(u.onboarding_completed === true ? "/(tabs)/discover" : "/onboarding/services");
    } catch (e) {
      Haptics.notificationAsync(Haptics.NotificationFeedbackType.Error);
      setError(getFriendlyMessage(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <KeyboardAwareScrollView
      style={{ flex: 1, backgroundColor: Colors.obsidian }}
      contentContainerStyle={[
        styles.container,
        { paddingTop: insets.top + 40, paddingBottom: insets.bottom + 24 },
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
      <Text style={styles.title}>Create your account</Text>
      <Text style={styles.subtitle}>
        Swipe your way to the perfect film or show, on the services you already pay for.
      </Text>

      <View style={styles.form}>
        <Text style={styles.label}>Name</Text>
        <TextInput
          style={styles.input}
          value={name}
          onChangeText={setName}
          placeholder="Your name"
          placeholderTextColor={Colors.textTertiary}
          autoComplete="name"
          textContentType="name"
          accessibilityLabel="Name"
          testID="register-name"
        />
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
          testID="register-email"
        />
        <Text style={styles.label}>Password</Text>
        <TextInput
          style={styles.input}
          value={password}
          onChangeText={setPassword}
          placeholder="At least 8 characters"
          placeholderTextColor={Colors.textTertiary}
          secureTextEntry
          autoComplete="new-password"
          textContentType="newPassword"
          accessibilityLabel="Password"
          testID="register-password"
        />
        <Text style={styles.label}>Date of birth (optional)</Text>
        <TextInput
          style={[styles.input, dobError && styles.inputError]}
          value={dob}
          onChangeText={(value) => setDob(formatDobInput(value))}
          placeholder="DD/MM/YYYY"
          placeholderTextColor={Colors.textTertiary}
          keyboardType="number-pad"
          maxLength={10}
          autoComplete="birthdate-full"
          accessibilityLabel="Date of birth, day month year"
          accessibilityHint="Enter eight digits. Slashes are added automatically."
          testID="register-dob"
          onSubmitEditing={submit}
        />
        {dobError ? (
          <Text style={styles.hint} accessibilityLiveRegion="polite">
            {dobError}
          </Text>
        ) : (
          <Text style={styles.hint}>Helps us tailor age-appropriate picks.</Text>
        )}

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
          accessibilityLabel="Create account"
          testID="register-submit"
        >
          {busy ? (
            <ActivityIndicator color="#fff" />
          ) : (
            <Text style={styles.primaryBtnText}>Create Account</Text>
          )}
        </Pressable>
      </View>

      <Pressable
        onPress={() => router.back()}
        style={styles.linkRow}
        accessibilityRole="button"
        accessibilityLabel="Back to sign in"
        testID="goto-login"
      >
        <Text style={styles.linkMuted}>Already have an account? </Text>
        <Text style={styles.link}>Sign in</Text>
      </Pressable>
    </KeyboardAwareScrollView>
  );
}

const styles = StyleSheet.create({
  container: { paddingHorizontal: 28, alignItems: "center" },
  mark: { width: 84, height: 84, marginBottom: 16 },
  title: {
    fontFamily: "Inter_800ExtraBold",
    fontSize: 26,
    color: Colors.text,
    marginBottom: 6,
    textAlign: "center",
  },
  subtitle: {
    fontFamily: "Inter_400Regular",
    fontSize: 15,
    color: Colors.textSecondary,
    marginBottom: 28,
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
  inputError: { borderColor: Colors.danger },
  hint: {
    fontFamily: "Inter_400Regular",
    fontSize: 12,
    color: Colors.textTertiary,
    marginTop: 6,
  },
  error: {
    fontFamily: "Inter_500Medium",
    color: Colors.danger,
    fontSize: 14,
    marginTop: 14,
    textAlign: "center",
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
  linkRow: { flexDirection: "row", marginTop: 24, minHeight: 44, alignItems: "center" },
  linkMuted: { fontFamily: "Inter_400Regular", color: Colors.textSecondary, fontSize: 15 },
  link: { fontFamily: "Inter_700Bold", color: Colors.amber, fontSize: 15 },
});
