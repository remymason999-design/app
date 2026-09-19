import { Ionicons } from "@expo/vector-icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import * as Haptics from "expo-haptics";
import { router } from "expo-router";
import { useEffect, useState } from "react";
import {
  ActivityIndicator,
  Alert,
  Platform,
  Pressable,
  RefreshControl,
  Share,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";

import { Image } from "expo-image";

import { ListError, ListLoading } from "@/components/lists/ListStates";
import { ScreenContainer } from "@/components/layout/ScreenContainer";
import { Colors } from "@/constants/colors";
import { useAuth } from "@/context/AuthContext";
import { getFriendlyMessage, resolveImageUrl } from "@/lib/api";
import {
  acceptFriendRequest,
  fetchFriends,
  fetchShareMe,
  fetchShareRequests,
  Friend,
  IncomingRequest,
  OutgoingRequest,
  rejectFriendRequest,
  removeFriend,
  sendFriendRequest,
  ShareMe,
  ShareRequests,
} from "@/lib/social-api";
import { analytics, EVENTS } from "@/lib/analytics";

function Avatar({
  name,
  picture,
  size = 40,
}: {
  name?: string | null;
  picture?: string | null;
  size?: number;
}) {
  const initial = (name || "?").slice(0, 1).toUpperCase();
  const [imgError, setImgError] = useState(false);
  const resolved = resolveImageUrl(picture);
  const showImage = !!resolved && !imgError;
  const dims = { width: size, height: size, borderRadius: size / 2 };
  return (
    <View style={[styles.avatar, dims]}>
      {showImage ? (
        <Image
          source={{ uri: resolved as string }}
          style={dims}
          contentFit="cover"
          onError={() => setImgError(true)}
        />
      ) : (
        <Text style={styles.avatarText}>{initial}</Text>
      )}
    </View>
  );
}

export default function FriendsScreen() {
  const { user } = useAuth();
  useEffect(() => {
    analytics.capture(EVENTS.FRIENDS_SCREEN_VIEWED, {}, { user });
  }, [user?.user_id]);
  const queryClient = useQueryClient();
  const [code, setCode] = useState("");
  const [banner, setBanner] = useState<string | null>(null);

  const meQ = useQuery<ShareMe>({
    queryKey: ["/share/me"],
    queryFn: fetchShareMe,
  });
  const friendsQ = useQuery<Friend[]>({
    queryKey: ["/share/friends"],
    queryFn: fetchFriends,
  });
  const requestsQ = useQuery<ShareRequests>({
    queryKey: ["/share/requests"],
    queryFn: fetchShareRequests,
  });

  const invalidateAll = () => {
    queryClient.invalidateQueries({ queryKey: ["/share/friends"] });
    queryClient.invalidateQueries({ queryKey: ["/share/requests"] });
    queryClient.invalidateQueries({ queryKey: ["/share/me"] });
  };

  const flash = (msg: string) => {
    setBanner(msg);
    setTimeout(() => setBanner((b) => (b === msg ? null : b)), 2400);
  };

  const sendM = useMutation({
    mutationFn: (c: string) => sendFriendRequest(c),
    onSuccess: (r) => {
      analytics.capture(EVENTS.FRIEND_REQUEST_SENT, { result: r.status }, { user });
      if (r.status === "sent") flash("Request sent");
      else if (r.status === "accepted")
        flash(`You're now sharing with ${r.friend?.name || "your friend"}`);
      else if (r.status === "already_friends") flash("Already sharing with them");
      else if (r.status === "already_requested") flash("Request already pending");
      setCode("");
      invalidateAll();
    },
    onError: (e) => flash(getFriendlyMessage(e)),
  });

  const acceptM = useMutation({
    mutationFn: (id: string) => acceptFriendRequest(id),
    onSuccess: () => {
      analytics.capture(EVENTS.FRIEND_REQUEST_ACCEPTED, { result: "accepted" }, { user });
      flash("Accepted");
      invalidateAll();
    },
    onError: (e) => flash(getFriendlyMessage(e)),
  });

  const rejectM = useMutation({
    mutationFn: (id: string) => rejectFriendRequest(id),
    onSuccess: invalidateAll,
    onError: () => flash("Couldn't reject"),
  });

  const unfriendM = useMutation({
    mutationFn: (id: string) => removeFriend(id),
    onSuccess: () => {
      analytics.capture(EVENTS.FRIEND_REMOVED, { result: "removed" }, { user });
      invalidateAll();
    },
    onError: () => flash("Couldn't remove"),
  });

  const mutating =
    sendM.isPending || acceptM.isPending || rejectM.isPending || unfriendM.isPending;

  const onSend = () => {
    const trimmed = code.trim().toUpperCase();
    if (!trimmed || sendM.isPending) return;
    if (Platform.OS !== "web") Haptics.selectionAsync();
    sendM.mutate(trimmed);
  };

  const onShare = async () => {
    const me = meQ.data;
    if (!me?.share_url) return;
    try {
      analytics.capture(EVENTS.SHARE_STARTED, { source: "friends" }, { user });
      const result = await Share.share({
        message: `Add me on WatchSmart — code ${me.share_code}\n${me.share_url}`,
      });
      analytics.capture(EVENTS.FRIEND_CODE_SHARED, {
        result: result.action === Share.dismissedAction ? "cancelled" : "shared",
      }, { user });
    } catch {
      // user cancelled
    }
  };

  const confirmUnfriend = (f: Friend) => {
    if (mutating) return;
    Alert.alert(
      "Remove friend",
      `Stop sharing watchlists with ${f.name}?`,
      [
        { text: "Cancel", style: "cancel" },
        {
          text: "Remove",
          style: "destructive",
          onPress: () => unfriendM.mutate(f.user_id),
        },
      ]
    );
  };

  const loading = meQ.isLoading || friendsQ.isLoading || requestsQ.isLoading;
  const errored = meQ.isError || friendsQ.isError || requestsQ.isError;

  if (loading) {
    return (
      <ScreenContainer>
        <ListLoading />
      </ScreenContainer>
    );
  }

  if (errored) {
    return (
      <ScreenContainer>
        <ListError
          message={getFriendlyMessage(meQ.error || friendsQ.error || requestsQ.error)}
          onRetry={() => {
            meQ.refetch();
            friendsQ.refetch();
            requestsQ.refetch();
          }}
          testID="friends-error"
        />
      </ScreenContainer>
    );
  }

  const me = meQ.data;
  const friends = friendsQ.data ?? [];
  const incoming: IncomingRequest[] = requestsQ.data?.incoming ?? [];
  const outgoing: OutgoingRequest[] = requestsQ.data?.outgoing ?? [];

  return (
    <ScreenContainer
      scroll
      keyboardShouldPersistTaps="handled"
      refreshControl={
        <RefreshControl
          refreshing={friendsQ.isRefetching || requestsQ.isRefetching}
          onRefresh={() => {
            friendsQ.refetch();
            requestsQ.refetch();
            meQ.refetch();
          }}
          tintColor={Colors.amber}
        />
      }
    >
      <Text style={styles.kicker}>Compare with friends</Text>
      <Text style={styles.h1}>Two heads.{"\n"}Better picks.</Text>

      {banner ? (
        <View style={styles.banner}>
          <Ionicons name="checkmark-circle" size={16} color={Colors.amber} />
          <Text style={styles.bannerText}>{banner}</Text>
        </View>
      ) : null}

      {/* My code card */}
      <View style={styles.card}>
        <Text style={styles.cardLabel}>Your code</Text>
        <Text style={styles.code} testID="my-share-code">
          {me?.share_code}
        </Text>
        <Pressable
          onPress={onShare}
          style={({ pressed }) => [styles.shareBtn, pressed && { opacity: 0.85 }]}
          accessibilityRole="button"
          accessibilityLabel="Share your code"
          testID="share-link-btn"
        >
          <Ionicons name="share-outline" size={16} color="#0B0500" />
          <Text style={styles.shareText}>Share your code</Text>
        </Pressable>
      </View>

      {/* Add by code */}
      <Text style={styles.sectionLabel}>Add a friend by code</Text>
      <View style={styles.addRow}>
        <TextInput
          value={code}
          onChangeText={(t) => setCode(t.toUpperCase().slice(0, 12))}
          placeholder="e.g. K7M3PQ"
          placeholderTextColor={Colors.textTertiary}
          autoCapitalize="characters"
          autoCorrect={false}
          style={styles.input}
          onSubmitEditing={onSend}
          returnKeyType="send"
          accessibilityLabel="Friend code"
          testID="friend-code-input"
        />
        <Pressable
          onPress={onSend}
          disabled={sendM.isPending || !code.trim()}
          style={[
            styles.sendBtn,
            (sendM.isPending || !code.trim()) && { opacity: 0.5 },
          ]}
          accessibilityRole="button"
          accessibilityLabel="Send friend request"
          testID="send-request-btn"
        >
          {sendM.isPending ? (
            <ActivityIndicator color="#0B0500" size="small" />
          ) : (
            <>
              <Ionicons name="person-add-outline" size={16} color="#0B0500" />
              <Text style={styles.shareText}>Send</Text>
            </>
          )}
        </Pressable>
      </View>

      {/* Incoming requests */}
      {incoming.length > 0 && (
        <View style={styles.section} testID="incoming-requests">
          <Text style={styles.h2}>
            Incoming requests <Text style={styles.badge}>{incoming.length}</Text>
          </Text>
          {incoming.map((r) => (
            <View key={r.request_id} style={styles.rowCard} testID={`incoming-${r.request_id}`}>
              <Avatar name={r.from?.name} picture={r.from?.picture} />
              <View style={styles.rowInfo}>
                <Text style={styles.rowName} numberOfLines={1}>
                  {r.from?.name || "Someone"}
                </Text>
                <Text style={styles.rowSub}>wants to compare watchlists</Text>
              </View>
              <Pressable
                onPress={() => !mutating && acceptM.mutate(r.request_id)}
                disabled={mutating}
                style={[styles.acceptBtn, mutating && { opacity: 0.5 }]}
                accessibilityRole="button"
                accessibilityLabel={`Accept request from ${r.from?.name || "someone"}`}
                testID={`accept-${r.request_id}`}
              >
                <Text style={styles.acceptText}>Accept</Text>
              </Pressable>
              <Pressable
                onPress={() => !mutating && rejectM.mutate(r.request_id)}
                disabled={mutating}
                style={[styles.iconBtn, mutating && { opacity: 0.5 }]}
                accessibilityRole="button"
                accessibilityLabel={`Reject request from ${r.from?.name || "someone"}`}
                testID={`reject-${r.request_id}`}
              >
                <Ionicons name="close" size={18} color={Colors.textSecondary} />
              </Pressable>
            </View>
          ))}
        </View>
      )}

      {/* Outgoing requests */}
      {outgoing.length > 0 && (
        <View style={styles.section} testID="outgoing-requests">
          <Text style={styles.h2muted}>Pending</Text>
          {outgoing.map((r) => (
            <View key={r.request_id} style={styles.rowCardMuted}>
              <Avatar name={r.to?.name} picture={r.to?.picture} />
              <View style={styles.rowInfo}>
                <Text style={styles.rowName} numberOfLines={1}>
                  {r.to?.name || "Friend"}
                </Text>
                <Text style={styles.rowSub}>Awaiting their response</Text>
              </View>
              <Ionicons name="hourglass-outline" size={16} color={Colors.textTertiary} />
            </View>
          ))}
        </View>
      )}

      {/* Friends list */}
      <View style={styles.section} testID="friends-list">
        <Text style={styles.h2}>Your watchlist friends</Text>
        {friends.length === 0 ? (
          <View style={styles.emptyCard}>
            <Text style={styles.rowSub}>
              Share your code with someone to start comparing watchlists.
            </Text>
          </View>
        ) : (
          friends.map((f) => (
            <View key={f.user_id} style={styles.rowCard} testID={`friend-${f.user_id}`}>
              <Avatar name={f.name} picture={f.picture} />
              <View style={styles.rowInfo}>
                <Text style={styles.rowName} numberOfLines={1}>
                  {f.name}
                </Text>
                <Text style={styles.rowSub}>{f.watchlist_size ?? 0} saved</Text>
              </View>
              <Pressable
                onPress={() =>
                  router.push({ pathname: "/compare/[id]", params: { id: f.user_id } })
                }
                style={({ pressed }) => [styles.acceptBtn, pressed && { opacity: 0.85 }]}
                accessibilityRole="button"
                accessibilityLabel={`Compare watchlists with ${f.name}`}
                testID={`compare-${f.user_id}`}
              >
                <Text style={styles.acceptText}>Compare</Text>
                <Ionicons name="arrow-forward" size={13} color="#0B0500" />
              </Pressable>
              <Pressable
                onPress={() => confirmUnfriend(f)}
                disabled={mutating}
                style={[styles.iconBtn, mutating && { opacity: 0.5 }]}
                accessibilityRole="button"
                accessibilityLabel={`Remove ${f.name}`}
                testID={`unfriend-${f.user_id}`}
              >
                <Ionicons name="trash-outline" size={16} color={Colors.textTertiary} />
              </Pressable>
            </View>
          ))
        )}
      </View>
    </ScreenContainer>
  );
}

const styles = StyleSheet.create({
  kicker: {
    fontFamily: "Inter_600SemiBold",
    fontSize: 11,
    letterSpacing: 2,
    textTransform: "uppercase",
    color: Colors.textTertiary,
  },
  h1: {
    fontFamily: "Inter_800ExtraBold",
    fontSize: 30,
    color: Colors.text,
    marginTop: 6,
    lineHeight: 34,
  },
  banner: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    backgroundColor: "rgba(255,122,24,0.12)",
    borderRadius: 12,
    padding: 12,
    marginTop: 16,
  },
  bannerText: { fontFamily: "Inter_500Medium", fontSize: 13, color: Colors.text, flex: 1 },
  card: {
    backgroundColor: Colors.surface,
    borderRadius: 22,
    borderWidth: 1,
    borderColor: Colors.border,
    padding: 20,
    marginTop: 24,
  },
  cardLabel: {
    fontFamily: "Inter_600SemiBold",
    fontSize: 11,
    letterSpacing: 1,
    textTransform: "uppercase",
    color: Colors.textTertiary,
  },
  code: {
    fontFamily: "Inter_800ExtraBold",
    fontSize: 40,
    letterSpacing: 6,
    color: Colors.text,
    marginTop: 4,
  },
  shareBtn: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 8,
    backgroundColor: Colors.amber,
    borderRadius: 14,
    paddingVertical: 12,
    marginTop: 16,
  },
  shareText: { fontFamily: "Inter_700Bold", fontSize: 14, color: "#0B0500" },
  sectionLabel: {
    fontFamily: "Inter_600SemiBold",
    fontSize: 11,
    letterSpacing: 1,
    textTransform: "uppercase",
    color: Colors.textTertiary,
    marginTop: 24,
    marginBottom: 10,
  },
  addRow: { flexDirection: "row", gap: 10 },
  input: {
    flex: 1,
    backgroundColor: Colors.velvet,
    borderWidth: 1,
    borderColor: Colors.border,
    borderRadius: 14,
    paddingHorizontal: 16,
    paddingVertical: 12,
    color: Colors.text,
    fontFamily: "Inter_600SemiBold",
    fontSize: 16,
    letterSpacing: 3,
  },
  sendBtn: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 6,
    backgroundColor: Colors.amber,
    borderRadius: 14,
    paddingHorizontal: 18,
    minWidth: 92,
  },
  section: { marginTop: 28 },
  h2: {
    fontFamily: "Inter_700Bold",
    fontSize: 16,
    color: Colors.text,
    marginBottom: 12,
  },
  h2muted: {
    fontFamily: "Inter_700Bold",
    fontSize: 16,
    color: Colors.textSecondary,
    marginBottom: 12,
  },
  badge: {
    fontFamily: "Inter_700Bold",
    fontSize: 12,
    color: Colors.amber,
  },
  rowCard: {
    flexDirection: "row",
    alignItems: "center",
    gap: 12,
    backgroundColor: Colors.surface,
    borderRadius: 18,
    borderWidth: 1,
    borderColor: Colors.border,
    padding: 14,
    marginBottom: 10,
  },
  rowCardMuted: {
    flexDirection: "row",
    alignItems: "center",
    gap: 12,
    backgroundColor: "rgba(255,255,255,0.02)",
    borderRadius: 18,
    borderWidth: 1,
    borderColor: Colors.border,
    padding: 14,
    marginBottom: 10,
  },
  rowInfo: { flex: 1, minWidth: 0 },
  rowName: { fontFamily: "Inter_600SemiBold", fontSize: 14, color: Colors.text },
  rowSub: { fontFamily: "Inter_400Regular", fontSize: 12, color: Colors.textTertiary, marginTop: 2 },
  acceptBtn: {
    flexDirection: "row",
    alignItems: "center",
    gap: 5,
    backgroundColor: Colors.amber,
    borderRadius: 12,
    paddingHorizontal: 14,
    paddingVertical: 9,
  },
  acceptText: { fontFamily: "Inter_700Bold", fontSize: 13, color: "#0B0500" },
  iconBtn: {
    width: 38,
    height: 38,
    borderRadius: 12,
    backgroundColor: Colors.velvet,
    alignItems: "center",
    justifyContent: "center",
  },
  emptyCard: {
    backgroundColor: Colors.surface,
    borderRadius: 18,
    borderWidth: 1,
    borderColor: Colors.border,
    padding: 18,
  },
  avatar: {
    backgroundColor: "rgba(255,122,24,0.15)",
    borderWidth: 1,
    borderColor: "rgba(255,122,24,0.35)",
    alignItems: "center",
    justifyContent: "center",
    overflow: "hidden",
  },
  avatarText: { fontFamily: "Inter_700Bold", fontSize: 16, color: Colors.amber },
});
