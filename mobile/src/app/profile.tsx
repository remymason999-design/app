import { Ionicons } from "@expo/vector-icons";
import { Image } from "expo-image";
import { ProviderLogo } from "@/components/ProviderLogo";
import * as Haptics from "expo-haptics";
import * as ImagePicker from "expo-image-picker";
import { router } from "expo-router";
import Constants from "expo-constants";
import { useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ActivityIndicator,
  Alert,
  Linking,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { PlanSelector } from "@/components/services/PlanSelector";
import { Colors } from "@/constants/colors";
import { Links } from "@/constants/links";
import { useAuth } from "@/context/AuthContext";
import { getFriendlyMessage, removeAvatar, resolveImageUrl, uploadAvatar } from "@/lib/api";
import {
  NotificationsResponse,
  clearAllNotifications,
  deleteAccount,
  fetchNotifications,
  markAllNotificationsRead,
  updatePreferences,
} from "@/lib/onboarding-api";
import { deriveTasteRows, onboardingAffinityDecay } from "@/lib/taste";
import { providerDisplayName } from "@/lib/providers";
import { analytics, EVENTS } from "@/lib/analytics";
import { deleteAccountWithAnalytics } from "@/lib/analytics-flow";
import {
  PricingService,
  SubscriptionPlanSelection,
  SubscriptionPlansMap,
  fetchPricingServices,
} from "@/lib/pricing-api";
import {
  PLUS_DEFAULT_CONFIG,
  PlusConfig,
  PlusInterest,
  fetchPlusConfig,
  fetchPlusInterest,
  trackPlusEvent,
} from "@/lib/plus-api";
import {
  PushState,
  enablePushNotifications,
  getPushState,
  unregisterPushNotifications,
} from "@/lib/push-notifications";

export default function Profile() {
  const { user, setUser, logout } = useAuth();
  const insets = useSafeAreaInsets();
  const qc = useQueryClient();
  const scrollRef = useRef<ScrollView>(null);
  const [busy, setBusy] = useState(false);
  const [savingService, setSavingService] = useState<string | null>(null);
  const [notifBusy, setNotifBusy] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [sheetService, setSheetService] = useState<PricingService | null>(null);
  const [avatarBusy, setAvatarBusy] = useState(false);
  const [pushState, setPushState] = useState<PushState>("disabled");
  const [pushBusy, setPushBusy] = useState(false);
  const plusCardLayout = useRef({ y: 0, height: 0 });
  const plusViewed = useRef(false);

  // The profile modal should always open scrolled to the very top.
  useEffect(() => {
    scrollRef.current?.scrollTo({ y: 0, animated: false });
    if (user?.user_id) void getPushState(user.user_id).then(setPushState);
  }, [user?.user_id]);

  const picture = resolveImageUrl(typeof user?.picture === "string" ? user.picture : null);
  const initial = (String(user?.name || user?.email || "?").trim()[0] || "?").toUpperCase();

  const applyAvatar = async (uri: string) => {
    if (avatarBusy) return;
    setAvatarBusy(true);
    try {
      Haptics.selectionAsync();
      const { picture: next } = await uploadAvatar(uri);
      setUser((u) => (u ? { ...u, picture: next } : u));
    } catch (e) {
      Alert.alert("Couldn't update photo", getFriendlyMessage(e));
    } finally {
      setAvatarBusy(false);
    }
  };

  const takePhoto = async () => {
    const perm = await ImagePicker.requestCameraPermissionsAsync();
    if (!perm.granted) {
      Alert.alert("Camera access needed", "Enable camera access in Settings to take a photo.");
      return;
    }
    const res = await ImagePicker.launchCameraAsync({
      allowsEditing: true,
      aspect: [1, 1],
      quality: 0.8,
    });
    if (!res.canceled && res.assets[0]?.uri) applyAvatar(res.assets[0].uri);
  };

  const chooseFromLibrary = async () => {
    const res = await ImagePicker.launchImageLibraryAsync({
      mediaTypes: "images",
      allowsEditing: true,
      aspect: [1, 1],
      quality: 0.8,
    });
    if (!res.canceled && res.assets[0]?.uri) applyAvatar(res.assets[0].uri);
  };

  const removePhoto = async () => {
    if (avatarBusy) return;
    setAvatarBusy(true);
    try {
      Haptics.selectionAsync();
      await removeAvatar();
      setUser((u) => (u ? { ...u, picture: null } : u));
    } catch (e) {
      Alert.alert("Couldn't remove photo", getFriendlyMessage(e));
    } finally {
      setAvatarBusy(false);
    }
  };

  const openPhotoActions = () => {
    if (avatarBusy) return;
    if (Platform.OS === "web") {
      // Alert.alert with multiple buttons is a no-op on react-native-web, so
      // fall back to the library picker directly (Remove has its own button).
      chooseFromLibrary();
      return;
    }
    const options: { text: string; onPress?: () => void; style?: "cancel" | "destructive" }[] = [
      { text: "Take photo", onPress: takePhoto },
      { text: "Choose from library", onPress: chooseFromLibrary },
    ];
    if (picture) options.push({ text: "Remove photo", style: "destructive", onPress: removePhoto });
    options.push({ text: "Cancel", style: "cancel" });
    Alert.alert("Profile photo", undefined, options);
  };

  const subscriptions = (user?.subscriptions as string[]) || [];
  const plans = (user?.subscription_plans as SubscriptionPlansMap) || {};

  const plusConfigQ = useQuery<PlusConfig>({
    queryKey: ["/monetization/config"],
    queryFn: fetchPlusConfig,
    staleTime: 5 * 60_000,
  });
  const plusInterestQ = useQuery<PlusInterest>({
    queryKey: ["/monetization/plus/interest", user?.user_id],
    queryFn: fetchPlusInterest,
    enabled: !!user?.user_id,
    staleTime: 60_000,
  });
  const plusConfig = plusConfigQ.data?.flags ? plusConfigQ.data : PLUS_DEFAULT_CONFIG;

  useEffect(() => {
    plusViewed.current = false;
    plusCardLayout.current = { y: 0, height: 0 };
  }, [user?.user_id]);

  const maybeTrackPlusCard = (event: {
    nativeEvent: {
      contentOffset: { y: number };
      layoutMeasurement: { height: number };
    };
  }) => {
    if (plusViewed.current || plusConfig.flags.plus_visible === false) return;
    const { y, height } = plusCardLayout.current;
    const { y: offset } = event.nativeEvent.contentOffset;
    const viewport = event.nativeEvent.layoutMeasurement.height;
    const visible = y < offset + viewport && y + height > offset;
    if (height > 0 && visible && Math.min(y + height, offset + viewport) - Math.max(y, offset) >= height * 0.5) {
      plusViewed.current = true;
      trackPlusEvent("plus_card_viewed", "profile");
    }
  };

  const servicesQuery = useQuery<PricingService[]>({
    queryKey: ["/pricing/services"],
    queryFn: fetchPricingServices,
  });
  const notifQuery = useQuery<NotificationsResponse>({
    queryKey: ["/notifications"],
    queryFn: fetchNotifications,
  });

  const signOut = async () => {
    setBusy(true);
    try {
      Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
      await logout();
      router.replace("/(auth)/login");
    } finally {
      setBusy(false);
    }
  };

  // Tapping a service opens the plan selector (both to toggle on and to change
  // an already-selected plan).
  const openService = (service: PricingService) => {
    if (savingService) return;
    Haptics.selectionAsync();
    setSheetService(service);
    analytics.capture(EVENTS.PROVIDER_PREFERENCES_VIEWED, { source: "profile" }, { user });
  };

  // Remove a service (long-press on a selected row).
  const removeService = async (id: string) => {
    if (savingService) return;
    setSavingService(id);
    const nextServices = subscriptions.filter((s) => s !== id);
    const nextPlans = { ...plans };
    delete nextPlans[id];
    try {
      Haptics.selectionAsync();
      const updated = await updatePreferences({
        services: nextServices,
        subscription_plans: nextPlans,
      });
      setUser(updated);
      analytics.capture(EVENTS.PROVIDER_REMOVED, { provider: id, provider_count: nextServices.length, source: "profile" }, { user: updated });
    } catch (e) {
      Alert.alert("Couldn't update", getFriendlyMessage(e));
    } finally {
      setSavingService(null);
    }
  };

  const onConfirmPlan = async (selection: SubscriptionPlanSelection) => {
    const service = sheetService;
    setSheetService(null);
    if (!service || savingService) return;
    setSavingService(service.id);
    const wasSelected = subscriptions.includes(service.id);
    const nextServices = wasSelected
      ? subscriptions
      : [...subscriptions, service.id];
    const nextPlans = { ...plans, [service.id]: selection };
    try {
      Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
      const updated = await updatePreferences({
        services: nextServices,
        subscription_plans: nextPlans,
      });
      setUser(updated);
      if (!wasSelected) {
        analytics.capture(EVENTS.PROVIDER_ADDED, { provider: service.id, provider_count: nextServices.length, source: "profile" }, { user: updated });
      }
    } catch (e) {
      Alert.alert("Couldn't update", getFriendlyMessage(e));
    } finally {
      setSavingService(null);
    }
  };

  const markRead = async () => {
    if (notifBusy) return;
    setNotifBusy(true);
    try {
      await markAllNotificationsRead();
      await qc.invalidateQueries({ queryKey: ["/notifications"] });
    } catch (e) {
      Alert.alert("Couldn't update", getFriendlyMessage(e));
    } finally {
      setNotifBusy(false);
    }
  };

  const clearNotifs = async () => {
    if (notifBusy) return;
    setNotifBusy(true);
    try {
      await clearAllNotifications();
      await qc.invalidateQueries({ queryKey: ["/notifications"] });
    } catch (e) {
      Alert.alert("Couldn't clear", getFriendlyMessage(e));
    } finally {
      setNotifBusy(false);
    }
  };

  const togglePush = async () => {
    if (pushBusy) return;
    if (pushState === "unavailable") {
      Alert.alert("Physical device required", "Push notifications are available in a native build on a physical device.");
      return;
    }
    if (pushState === "configuration-required") {
      Alert.alert(
        "Native build required",
        "Push notifications will be available after the EAS project and notification credentials are configured in a new native build."
      );
      return;
    }
    if (pushState === "denied") {
      Alert.alert(
        "Notifications are off",
        "Enable notifications for WatchSmart in your device settings.",
        [
          { text: "Cancel", style: "cancel" },
          { text: "Open Settings", onPress: () => Linking.openSettings() },
        ]
      );
      return;
    }
    setPushBusy(true);
    try {
      if (pushState === "enabled") {
        await unregisterPushNotifications();
        setPushState("disabled");
      } else {
        await enablePushNotifications(user!.user_id);
        setPushState("enabled");
      }
      Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success);
    } catch (error) {
      const next = user?.user_id
        ? await getPushState(user.user_id)
        : "disabled";
      setPushState(next);
      Alert.alert(
        "Couldn't update notifications",
        error instanceof Error ? error.message : getFriendlyMessage(error)
      );
    } finally {
      setPushBusy(false);
    }
  };

  const openLink = async (url: string) => {
    try {
      await Linking.openURL(url);
    } catch {
      Alert.alert("Couldn't open link", "Please try again later.");
    }
  };

  const confirmDelete = () => {
    Alert.alert(
      "Delete account?",
      "This permanently deletes your account, watchlist and all data. This cannot be undone.",
      [
        { text: "Cancel", style: "cancel" },
        {
          text: "Continue",
          style: "destructive",
          onPress: () =>
            Alert.alert(
              "Are you absolutely sure?",
              "There is no way to recover your account after this.",
              [
                { text: "Cancel", style: "cancel" },
                { text: "Delete forever", style: "destructive", onPress: runDelete },
              ]
            ),
        },
      ]
    );
  };

  const runDelete = async () => {
    if (deleting) return;
    setDeleting(true);
    try {
      Haptics.notificationAsync(Haptics.NotificationFeedbackType.Warning);
      await deleteAccountWithAnalytics(
        () => deleteAccount(),
        analytics,
        user,
        logout
      );
      router.replace("/(auth)/login");
    } catch (e) {
      setDeleting(false);
      Alert.alert("Couldn't delete account", getFriendlyMessage(e));
    }
  };

  const appVersion = Constants.expoConfig?.version ?? "—";
  const buildNumber = Constants.expoConfig?.ios?.buildNumber ?? null;
  const notifications = notifQuery.data?.items ?? [];
  const unread = notifQuery.data?.unread ?? 0;
  const savedCount = Array.isArray(user?.saved) ? user.saved.length : 0;
  const watchedCount = Array.isArray(user?.watched) ? user.watched.length : 0;
  const tasteRows = deriveTasteRows({
    genreWeights: user?.genre_weights,
    onboardingGenreWeights: user?.onboarding_genre_weights,
    onboardingDecay: onboardingAffinityDecay(
      Number(user?.post_onboarding_interactions) || 0
    ),
    selectedGenres: user?.genres,
  });

  return (
    <View style={styles.root}>
      <ScrollView
        ref={scrollRef}
        onScroll={maybeTrackPlusCard}
        scrollEventThrottle={100}
        contentContainerStyle={{
          paddingHorizontal: 24,
          paddingTop: insets.top + 8,
          paddingBottom: insets.bottom + 32,
        }}
      >
        <View style={styles.header}>
          <Text style={styles.title}>Profile</Text>
          <Pressable
            onPress={() => router.back()}
            hitSlop={12}
            style={styles.closeBtn}
            accessibilityRole="button"
            accessibilityLabel="Close profile"
            testID="close-profile"
          >
            <Ionicons name="close" size={24} color={Colors.textSecondary} />
          </Pressable>
        </View>

        <View style={styles.card}>
          <Pressable
            onPress={openPhotoActions}
            disabled={avatarBusy}
            style={styles.bigAvatar}
            accessibilityRole="button"
            accessibilityLabel="Change profile photo"
            testID="profile-avatar-edit"
          >
            {picture ? (
              <Image
                source={{ uri: picture }}
                style={styles.bigAvatarImg}
                contentFit="cover"
                cachePolicy="none"
              />
            ) : (
              <Text style={styles.bigAvatarText}>{initial}</Text>
            )}
            {avatarBusy ? (
              <View style={styles.avatarOverlay}>
                <ActivityIndicator color="#0B0500" />
              </View>
            ) : null}
          </Pressable>
          <Text style={styles.name}>{String(user?.name || "WatchSmart member")}</Text>
          <Text style={styles.email}>{String(user?.email || "")}</Text>
          <Pressable
            onPress={openPhotoActions}
            disabled={avatarBusy}
            hitSlop={8}
            style={({ pressed }) => [styles.editPhotoBtn, pressed && { opacity: 0.7 }]}
            accessibilityRole="button"
            accessibilityLabel="Edit photo"
            testID="edit-photo-btn"
          >
            <Ionicons name="camera-outline" size={15} color={Colors.amber} />
            <Text style={styles.editPhotoText}>Edit photo</Text>
          </Pressable>
          {picture ? (
            <Pressable
              onPress={removePhoto}
              disabled={avatarBusy}
              hitSlop={8}
              style={({ pressed }) => [styles.editPhotoBtn, pressed && { opacity: 0.7 }]}
              accessibilityRole="button"
              accessibilityLabel="Remove photo"
              testID="remove-photo-btn"
            >
              <Ionicons name="trash-outline" size={15} color="#FF6B6B" />
              <Text style={[styles.editPhotoText, { color: "#FF6B6B" }]}>Remove photo</Text>
            </Pressable>
          ) : null}
        </View>

        <View style={styles.statsRow} testID="profile-stats">
          <ProfileStat label="Saved" value={savedCount} icon="bookmark-outline" />
          <ProfileStat label="Watched" value={watchedCount} icon="eye-outline" />
          <ProfileStat label="Services" value={subscriptions.length} icon="tv-outline" />
        </View>

        <Text style={styles.sectionTitle}>What we’ve learned about you</Text>
        <View style={styles.learningCard} testID="learning-card">
          {tasteRows.length === 0 ? (
            <Text style={styles.learningEmpty}>
              Choose a few genres or make a deliberate taste choice to start shaping your picks.
            </Text>
          ) : (
            <>
              <Text style={styles.learningEyebrow}>YOUR TASTE SO FAR</Text>
              <View style={styles.tasteList}>
                {tasteRows.map((row) => (
                  <View key={row.genre} style={styles.tasteRow} testID={`learned-${row.genre}`}>
                    <Text style={styles.tasteGenre} numberOfLines={1}>{row.genre}</Text>
                    <View style={styles.tasteBarTrack}>
                      <View style={[styles.tasteBar, { width: `${row.barPercent}%` }]} />
                    </View>
                    <Text style={styles.tasteStrength}>{row.strength}</Text>
                  </View>
                ))}
              </View>
            </>
          )}
        </View>

        {plusConfig.flags.plus_visible !== false ? (
          <>
            <Text style={styles.sectionTitle}>WatchSmart+</Text>
            <Pressable
              onLayout={(event) => {
                plusCardLayout.current = {
                  y: event.nativeEvent.layout.y,
                  height: event.nativeEvent.layout.height,
                };
              }}
              onPress={() => {
                trackPlusEvent("plus_card_clicked", "profile");
                // Expo's checked-in route declaration is regenerated by the
                // router dev server; keep the new additive route type-safe at
                // runtime while older generated declarations catch up.
                router.push({ pathname: "/plus" as any, params: { source: "profile" } });
              }}
              style={({ pressed }) => [styles.plusCard, pressed && { opacity: 0.85 }]}
              accessibilityRole="button"
              accessibilityLabel="Open WatchSmart Plus Coming Soon preview"
              testID="plus-profile-card"
            >
              <View style={styles.plusIcon}>
                <Ionicons name="sparkles" size={20} color={Colors.obsidian} />
              </View>
              <View style={styles.plusCopy}>
                <View style={styles.plusTitleRow}>
                  <Text style={styles.plusTitle}>WatchSmart+</Text>
                  <Text style={styles.plusBadge}>COMING SOON</Text>
                </View>
                <Text style={styles.plusSubtitle}>
                  More ways to find what you love, watch together and get more from your streaming subscriptions.
                </Text>
                {plusInterestQ.data?.interested ? (
                  <Text style={styles.plusOnList}>You&apos;re on the list.</Text>
                ) : null}
              </View>
              <Ionicons name="chevron-forward" size={18} color={Colors.textTertiary} />
            </Pressable>
          </>
        ) : null}

        {/* Streaming services */}
        <Text style={styles.sectionTitle}>Streaming services</Text>
        {servicesQuery.isLoading ? (
          <View style={styles.centerRow}>
            <ActivityIndicator color={Colors.amber} />
          </View>
        ) : servicesQuery.isError ? (
          <View style={styles.centerRow}>
            <Text style={styles.errorText}>Couldn&apos;t load services.</Text>
            <Pressable
              onPress={() => servicesQuery.refetch()}
              style={styles.retryBtn}
              accessibilityRole="button"
              accessibilityLabel="Retry loading services"
            >
              <Text style={styles.retryText}>Retry</Text>
            </Pressable>
          </View>
        ) : (
          <View style={styles.grid}>
            {(servicesQuery.data ?? []).map((s) => {
              const on = subscriptions.includes(s.id);
              const isSaving = savingService === s.id;
              const name = providerDisplayName(s.id, s.name);
              const sel = plans[s.id];
              const planLabel = on
                ? sel?.plan_id
                  ? `${sel.effective_monthly_cost > 0 ? `£${sel.effective_monthly_cost.toFixed(2)}/mo` : "£0/mo"} · Change plan`
                  : "Choose plan"
                : "Tap to add";
              return (
                <Pressable
                  key={s.id}
                  onPress={() => openService(s)}
                  onLongPress={() => {
                    if (on) removeService(s.id);
                  }}
                  disabled={!!savingService}
                  style={[
                    styles.serviceRow,
                    on && styles.serviceRowOn,
                    !!savingService && !isSaving && styles.btnDisabled,
                  ]}
                  accessibilityRole="button"
                  accessibilityState={{ selected: on }}
                  accessibilityLabel={
                    on
                      ? `${name}, selected. Tap to change plan, long press to remove.`
                      : `${name}, tap to add and choose a plan`
                  }
                >
                  <ProviderLogo sid={s.id} name={name} logoUrl={s.logo_path} size={34} radius={9} />
                  <View style={{ flex: 1 }}>
                    <Text style={styles.serviceName}>{name}</Text>
                    <Text style={styles.servicePrice}>{planLabel}</Text>
                  </View>
                  {isSaving ? (
                    <ActivityIndicator color={Colors.amber} size="small" />
                  ) : on ? (
                    <Ionicons name="checkmark-circle" size={20} color={Colors.amber} />
                  ) : null}
                </Pressable>
              );
            })}
          </View>
        )}

        {/* Notifications */}
        <View style={styles.sectionHeaderRow}>
          <Text style={styles.sectionTitle}>
            Notifications{unread > 0 ? ` (${unread})` : ""}
          </Text>
          {notifications.length > 0 ? (
            <View style={styles.notifActions}>
              <Pressable
                onPress={markRead}
                disabled={notifBusy || unread === 0}
                hitSlop={8}
                accessibilityRole="button"
                accessibilityLabel="Mark all notifications read"
              >
                <Text
                  style={[styles.linkAction, (notifBusy || unread === 0) && styles.dim]}
                >
                  Mark read
                </Text>
              </Pressable>
              <Pressable
                onPress={clearNotifs}
                disabled={notifBusy}
                hitSlop={8}
                accessibilityRole="button"
                accessibilityLabel="Clear all notifications"
              >
                <Text style={[styles.linkAction, notifBusy && styles.dim]}>Clear</Text>
              </Pressable>
            </View>
          ) : null}
        </View>
        <Pressable
          onPress={togglePush}
          disabled={pushBusy}
          accessibilityRole="switch"
          accessibilityState={{ checked: pushState === "enabled", disabled: pushBusy }}
          accessibilityLabel="Push notifications"
          style={({ pressed }) => [
            styles.pushControl,
            pushState === "enabled" && styles.pushControlOn,
            (pressed || pushBusy) && styles.dim,
          ]}
        >
          <View style={styles.pushIcon}>
            <Ionicons
              name={pushState === "enabled" ? "notifications" : "notifications-outline"}
              size={20}
              color={pushState === "enabled" ? Colors.amber : Colors.textSecondary}
            />
          </View>
          <View style={{ flex: 1 }}>
            <Text style={styles.pushTitle}>Push notifications</Text>
            <Text style={styles.pushBody}>
              {pushState === "enabled"
                ? "Friend requests and important account updates are on."
                : pushState === "denied"
                  ? "Off in device settings."
                  : pushState === "configuration-required"
                    ? "Requires notification credentials in a new native build."
                  : pushState === "unavailable"
                    ? "Available in the native app on a physical device."
                    : "Get friend requests and important account updates."}
            </Text>
          </View>
          {pushBusy ? (
            <ActivityIndicator size="small" color={Colors.amber} />
          ) : (
            <Ionicons
              name={pushState === "enabled" ? "checkmark-circle" : "chevron-forward"}
              size={20}
              color={pushState === "enabled" ? Colors.amber : Colors.textTertiary}
            />
          )}
        </Pressable>
        {notifQuery.isLoading ? (
          <View style={styles.centerRow}>
            <ActivityIndicator color={Colors.amber} />
          </View>
        ) : notifQuery.isError ? (
          <View style={styles.centerRow}>
            <Text style={styles.errorText}>Couldn&apos;t load notifications.</Text>
            <Pressable
              onPress={() => notifQuery.refetch()}
              style={styles.retryBtn}
              accessibilityRole="button"
              accessibilityLabel="Retry loading notifications"
            >
              <Text style={styles.retryText}>Retry</Text>
            </Pressable>
          </View>
        ) : notifications.length === 0 ? (
          <View style={styles.emptyCard}>
            <Ionicons name="notifications-outline" size={22} color={Colors.textTertiary} />
            <Text style={styles.emptyText}>You&apos;re all caught up.</Text>
          </View>
        ) : (
          <View style={styles.notifList}>
            {notifications.map((n, i) => (
              <View
                key={n.notification_id ?? `${n.created_at ?? ""}-${i}`}
                style={[styles.notifItem, !n.read && styles.notifUnread]}
              >
                <View style={{ flex: 1 }}>
                  <Text style={styles.notifTitle}>{n.title || "Notification"}</Text>
                  {n.body ? <Text style={styles.notifBody}>{n.body}</Text> : null}
                </View>
                {!n.read ? <View style={styles.unreadDot} /> : null}
              </View>
            ))}
          </View>
        )}

        {/* Help */}
        <Text style={styles.sectionTitle}>Help</Text>
        <View style={styles.linkGroup}>
          <Pressable
            onPress={() => router.push({ pathname: "/tutorial", params: { replay: "1" } })}
            style={({ pressed }) => [styles.linkRow, pressed && { opacity: 0.7 }]}
            accessibilityRole="button"
            accessibilityLabel="Replay tutorial"
            testID="replay-tutorial"
          >
            <Ionicons name="play-circle-outline" size={20} color={Colors.textSecondary} />
            <Text style={styles.linkLabel}>Replay tutorial</Text>
            <Ionicons name="chevron-forward" size={16} color={Colors.textTertiary} />
          </Pressable>
        </View>

        {/* Links */}
        <Text style={styles.sectionTitle}>About &amp; legal</Text>
        <View style={styles.linkGroup}>
          <LinkRow
            icon="shield-checkmark-outline"
            label="Privacy Policy"
            onPress={() => openLink(Links.privacy)}
          />
          <LinkRow
            icon="document-text-outline"
            label="Terms of Service"
            onPress={() => openLink(Links.terms)}
          />
          <LinkRow
            icon="help-circle-outline"
            label="Support"
            onPress={() => openLink(Links.support)}
            last
          />
        </View>

        {/* Sign out */}
        <Pressable
          style={({ pressed }) => [styles.signOut, pressed && { opacity: 0.8 }]}
          onPress={signOut}
          disabled={busy}
          accessibilityRole="button"
          accessibilityLabel="Sign out"
          testID="sign-out"
        >
          {busy ? (
            <ActivityIndicator color={Colors.danger} />
          ) : (
            <Text style={styles.signOutText}>Sign Out</Text>
          )}
        </Pressable>

        {/* Delete account */}
        <Pressable
          onPress={confirmDelete}
          disabled={deleting}
          style={styles.deleteBtn}
          accessibilityRole="button"
          accessibilityLabel="Delete account"
          testID="delete-account"
        >
          {deleting ? (
            <ActivityIndicator color={Colors.textTertiary} />
          ) : (
            <Text style={styles.deleteText}>Delete my account</Text>
          )}
        </Pressable>

        {/* Version + attribution */}
        <View style={styles.footer}>
          <Text style={styles.version}>
            Version {appVersion}
            {buildNumber ? ` (${buildNumber})` : ""}
          </Text>
          <Text style={styles.attribution}>Film &amp; TV data provided by TMDB</Text>
        </View>
      </ScrollView>

      <PlanSelector
        visible={!!sheetService}
        service={sheetService}
        current={sheetService ? plans[sheetService.id] ?? null : null}
        onConfirm={onConfirmPlan}
        onClose={() => setSheetService(null)}
      />
    </View>
  );
}

function ProfileStat({
  label,
  value,
  icon,
}: {
  label: string;
  value: number;
  icon: keyof typeof Ionicons.glyphMap;
}) {
  return (
    <View style={styles.statCard}>
      <Ionicons name={icon} size={16} color={Colors.amber} />
      <Text style={styles.statValue}>{value}</Text>
      <Text style={styles.statLabel}>{label}</Text>
    </View>
  );
}

function LinkRow({
  icon,
  label,
  onPress,
  last,
}: {
  icon: keyof typeof Ionicons.glyphMap;
  label: string;
  onPress: () => void;
  last?: boolean;
}) {
  return (
    <Pressable
      onPress={onPress}
      style={({ pressed }) => [
        styles.linkRow,
        !last && styles.linkRowBorder,
        pressed && { opacity: 0.7 },
      ]}
      accessibilityRole="link"
      accessibilityLabel={label}
    >
      <Ionicons name={icon} size={20} color={Colors.textSecondary} />
      <Text style={styles.linkLabel}>{label}</Text>
      <Ionicons name="open-outline" size={16} color={Colors.textTertiary} />
    </Pressable>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: Colors.obsidian },
  header: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    minHeight: 40,
    marginBottom: 16,
  },
  title: { fontFamily: "Inter_800ExtraBold", fontSize: 24, color: Colors.text },
  closeBtn: {
    width: 40,
    height: 40,
    alignItems: "center",
    justifyContent: "center",
    marginRight: -8,
  },
  card: {
    backgroundColor: Colors.velvet,
    borderColor: Colors.border,
    borderWidth: 1,
    borderRadius: 20,
    alignItems: "center",
    paddingVertical: 24,
    marginBottom: 8,
  },
  statsRow: { flexDirection: "row", gap: 8, marginTop: 8 },
  statCard: {
    flex: 1,
    alignItems: "center",
    gap: 5,
    paddingVertical: 12,
    borderRadius: 16,
    borderWidth: 1,
    borderColor: Colors.border,
    backgroundColor: "rgba(255,255,255,0.03)",
  },
  statValue: { fontFamily: "Inter_800ExtraBold", fontSize: 21, color: Colors.text },
  statLabel: {
    fontFamily: "Inter_500Medium",
    fontSize: 10,
    letterSpacing: 0.8,
    textTransform: "uppercase",
    color: Colors.textTertiary,
  },
  learningCard: {
    padding: 16,
    borderRadius: 18,
    borderWidth: 1,
    borderColor: Colors.border,
    backgroundColor: Colors.velvet,
  },
  plusCard: {
    flexDirection: "row",
    alignItems: "flex-start",
    gap: 11,
    padding: 16,
    borderRadius: 18,
    borderWidth: 1,
    borderColor: "rgba(255,122,24,0.35)",
    backgroundColor: "rgba(255,122,24,0.10)",
  },
  plusIcon: {
    width: 40,
    height: 40,
    borderRadius: 13,
    backgroundColor: Colors.amber,
    alignItems: "center",
    justifyContent: "center",
  },
  plusCopy: { flex: 1 },
  plusTitleRow: { flexDirection: "row", alignItems: "center", flexWrap: "wrap", gap: 7 },
  plusTitle: { fontFamily: "Inter_700Bold", fontSize: 16, color: Colors.text },
  plusBadge: {
    fontFamily: "Inter_700Bold",
    fontSize: 9,
    letterSpacing: 0.8,
    color: Colors.amber,
    borderWidth: 1,
    borderColor: "rgba(255,122,24,0.35)",
    borderRadius: 999,
    paddingHorizontal: 7,
    paddingVertical: 3,
  },
  plusSubtitle: {
    fontFamily: "Inter_400Regular",
    fontSize: 13,
    lineHeight: 19,
    color: Colors.textSecondary,
    marginTop: 8,
  },
  plusOnList: {
    fontFamily: "Inter_600SemiBold",
    fontSize: 12,
    color: Colors.success,
    marginTop: 8,
  },
  learningEmpty: {
    fontFamily: "Inter_400Regular",
    fontSize: 13,
    lineHeight: 19,
    color: Colors.textSecondary,
  },
  learningEyebrow: {
    fontFamily: "Inter_600SemiBold",
    fontSize: 10,
    letterSpacing: 1.4,
    color: Colors.textTertiary,
    marginBottom: 12,
  },
  tasteList: { gap: 11 },
  tasteRow: { flexDirection: "row", alignItems: "center", gap: 8 },
  tasteGenre: {
    width: 76,
    fontFamily: "Inter_600SemiBold",
    fontSize: 12,
    color: Colors.text,
  },
  tasteBarTrack: {
    flex: 1,
    height: 6,
    borderRadius: 999,
    overflow: "hidden",
    backgroundColor: "rgba(255,255,255,0.08)",
  },
  tasteBar: { height: "100%", borderRadius: 999, backgroundColor: Colors.amber },
  tasteStrength: {
    width: 86,
    fontFamily: "Inter_500Medium",
    fontSize: 10,
    color: Colors.textTertiary,
    textAlign: "right",
  },
  bigAvatar: {
    width: 84,
    height: 84,
    borderRadius: 42,
    backgroundColor: Colors.amber,
    alignItems: "center",
    justifyContent: "center",
    marginBottom: 14,
    overflow: "hidden",
  },
  bigAvatarImg: { width: "100%", height: "100%" },
  avatarOverlay: {
    ...StyleSheet.absoluteFillObject,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: "rgba(255,122,24,0.55)",
  },
  bigAvatarText: { fontFamily: "Inter_800ExtraBold", fontSize: 34, color: "#0B0500" },
  editPhotoBtn: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    marginTop: 12,
  },
  editPhotoText: { fontFamily: "Inter_600SemiBold", fontSize: 13, color: Colors.amber },
  name: { fontFamily: "Inter_700Bold", fontSize: 19, color: Colors.text, marginTop: 2 },
  email: {
    fontFamily: "Inter_400Regular",
    fontSize: 14,
    color: Colors.textSecondary,
    marginTop: 4,
  },
  sectionTitle: {
    fontFamily: "Inter_700Bold",
    fontSize: 15,
    color: Colors.text,
    marginTop: 28,
    marginBottom: 12,
  },
  sectionHeaderRow: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
  },
  notifActions: { flexDirection: "row", gap: 16, marginTop: 28, marginBottom: 12 },
  linkAction: { fontFamily: "Inter_600SemiBold", fontSize: 13, color: Colors.amber },
  dim: { opacity: 0.4 },
  centerRow: { alignItems: "center", justifyContent: "center", paddingVertical: 24, gap: 12 },
  grid: { gap: 8 },
  serviceRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 12,
    padding: 12,
    borderRadius: 14,
    borderWidth: 1,
    borderColor: Colors.border,
    backgroundColor: "rgba(255,255,255,0.03)",
  },
  serviceRowOn: {
    borderColor: Colors.amber,
    backgroundColor: "rgba(255,122,24,0.10)",
  },
  serviceName: { fontFamily: "Inter_600SemiBold", fontSize: 15, color: Colors.text },
  servicePrice: {
    fontFamily: "Inter_400Regular",
    fontSize: 12,
    color: Colors.textTertiary,
    marginTop: 2,
  },
  notifList: { gap: 8 },
  pushControl: {
    flexDirection: "row",
    alignItems: "center",
    gap: 12,
    padding: 14,
    marginBottom: 10,
    borderRadius: 14,
    borderWidth: 1,
    borderColor: Colors.border,
    backgroundColor: "rgba(255,255,255,0.03)",
  },
  pushControlOn: {
    borderColor: "rgba(255,122,24,0.35)",
    backgroundColor: "rgba(255,122,24,0.08)",
  },
  pushIcon: { width: 28, alignItems: "center" },
  pushTitle: { fontFamily: "Inter_600SemiBold", fontSize: 14, color: Colors.text },
  pushBody: {
    fontFamily: "Inter_400Regular",
    fontSize: 12,
    lineHeight: 17,
    color: Colors.textSecondary,
    marginTop: 2,
  },
  notifItem: {
    flexDirection: "row",
    alignItems: "flex-start",
    gap: 10,
    padding: 14,
    borderRadius: 14,
    borderWidth: 1,
    borderColor: Colors.border,
    backgroundColor: "rgba(255,255,255,0.03)",
  },
  notifUnread: { borderColor: "rgba(255,122,24,0.35)" },
  notifTitle: { fontFamily: "Inter_600SemiBold", fontSize: 14, color: Colors.text },
  notifBody: {
    fontFamily: "Inter_400Regular",
    fontSize: 13,
    color: Colors.textSecondary,
    marginTop: 3,
    lineHeight: 18,
  },
  unreadDot: {
    width: 8,
    height: 8,
    borderRadius: 4,
    backgroundColor: Colors.amber,
    marginTop: 5,
  },
  emptyCard: {
    alignItems: "center",
    gap: 8,
    paddingVertical: 24,
    borderRadius: 14,
    borderWidth: 1,
    borderColor: Colors.border,
    backgroundColor: "rgba(255,255,255,0.02)",
  },
  emptyText: { fontFamily: "Inter_400Regular", fontSize: 13, color: Colors.textTertiary },
  linkGroup: {
    borderWidth: 1,
    borderColor: Colors.border,
    borderRadius: 16,
    backgroundColor: "rgba(255,255,255,0.03)",
    overflow: "hidden",
  },
  linkRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 12,
    paddingHorizontal: 16,
    paddingVertical: 15,
  },
  linkRowBorder: { borderBottomWidth: 1, borderBottomColor: Colors.border },
  linkLabel: { flex: 1, fontFamily: "Inter_500Medium", fontSize: 15, color: Colors.text },
  signOut: {
    minHeight: 48,
    alignItems: "center",
    justifyContent: "center",
    marginTop: 28,
  },
  signOutText: { fontFamily: "Inter_600SemiBold", fontSize: 16, color: Colors.danger },
  deleteBtn: {
    minHeight: 44,
    alignItems: "center",
    justifyContent: "center",
    marginTop: 4,
  },
  deleteText: { fontFamily: "Inter_500Medium", fontSize: 13, color: Colors.textTertiary },
  footer: { alignItems: "center", gap: 6, marginTop: 24 },
  version: { fontFamily: "Inter_400Regular", fontSize: 12, color: Colors.textTertiary },
  attribution: { fontFamily: "Inter_400Regular", fontSize: 12, color: Colors.textTertiary },
  retryBtn: {
    borderWidth: 1,
    borderColor: Colors.border,
    borderRadius: 12,
    paddingHorizontal: 20,
    paddingVertical: 8,
  },
  retryText: { fontFamily: "Inter_600SemiBold", fontSize: 13, color: Colors.text },
  errorText: { fontFamily: "Inter_500Medium", fontSize: 13, color: Colors.danger },
  btnDisabled: { opacity: 0.5 },
});
