import Constants from "expo-constants";
import * as Crypto from "expo-crypto";
import * as Device from "expo-device";
import * as Notifications from "expo-notifications";
import { Href, router } from "expo-router";
import * as SecureStore from "expo-secure-store";
import { Platform } from "react-native";

import { api } from "@/lib/api";

const PUSH_TOKEN_KEY = "ws_expo_push_token";
const PUSH_OPTED_USER_KEY = "ws_push_opted_user";
const PUSH_INSTALLATION_KEY = "ws_push_installation";
const PUSH_UNREGISTER_SECRET_KEY = "ws_push_unregister_secret";
const PUSH_UNREGISTER_PENDING_KEY = "ws_push_unregister_pending";

export type PushState =
  | "enabled"
  | "disabled"
  | "denied"
  | "unavailable"
  | "configuration-required";
let operationChain: Promise<unknown> = Promise.resolve();

if (Platform.OS !== "web") {
  Notifications.setNotificationHandler({
    handleNotification: async () => ({
      shouldShowBanner: true,
      shouldShowList: true,
      shouldPlaySound: true,
      shouldSetBadge: false,
    }),
  });
}

function configuredProjectId(): string | null {
  return (
    Constants.expoConfig?.extra?.eas?.projectId ??
    Constants.easConfig?.projectId ??
    null
  );
}

function projectId(): string {
  const id = configuredProjectId();
  if (!id) {
    throw new Error("Push notifications need an EAS project before a native build.");
  }
  return id;
}

async function currentToken(): Promise<string | null> {
  if (Platform.OS === "web") return null;
  return SecureStore.getItemAsync(PUSH_TOKEN_KEY);
}

function randomId(prefix: string): string {
  return `${prefix}_${Crypto.randomUUID()}_${Crypto.randomUUID()}`;
}

async function installationIdentity(): Promise<{
  installationId: string;
  unregisterSecret: string;
}> {
  let installationId = await SecureStore.getItemAsync(PUSH_INSTALLATION_KEY);
  let unregisterSecret = await SecureStore.getItemAsync(
    PUSH_UNREGISTER_SECRET_KEY
  );
  if (!installationId) {
    installationId = randomId("installation");
    await SecureStore.setItemAsync(PUSH_INSTALLATION_KEY, installationId);
  }
  if (!unregisterSecret) {
    unregisterSecret = randomId("unregister_secret");
    await SecureStore.setItemAsync(
      PUSH_UNREGISTER_SECRET_KEY,
      unregisterSecret
    );
  }
  return { installationId, unregisterSecret };
}

function serialize<T>(operation: () => Promise<T>): Promise<T> {
  const next = operationChain.then(operation, operation);
  operationChain = next.catch(() => undefined);
  return next;
}

async function registerToken(userId: string): Promise<void> {
  if (Platform.OS === "android") {
    await Notifications.setNotificationChannelAsync("default", {
      name: "WatchSmart updates",
      importance: Notifications.AndroidImportance.HIGH,
      vibrationPattern: [0, 250, 250, 250],
      lightColor: "#FF7A18",
    });
  }
  const token = (
    await Notifications.getExpoPushTokenAsync({ projectId: projectId() })
  ).data;
  const { installationId, unregisterSecret } = await installationIdentity();
  await api.post("/notifications/push-device", {
    expo_token: token,
    installation_id: installationId,
    unregister_secret: unregisterSecret,
    platform: Platform.OS,
    app_version: Constants.expoConfig?.version ?? null,
  });
  await SecureStore.setItemAsync(PUSH_TOKEN_KEY, token);
  await SecureStore.setItemAsync(PUSH_OPTED_USER_KEY, userId);
  await SecureStore.deleteItemAsync(PUSH_UNREGISTER_PENDING_KEY);
}

export async function getPushState(userId: string): Promise<PushState> {
  if (Platform.OS === "web" || !Device.isDevice) return "unavailable";
  if (!configuredProjectId()) return "configuration-required";
  const permission = await Notifications.getPermissionsAsync();
  if (permission.status === "denied") return "denied";
  if (permission.status !== "granted") return "disabled";
  if ((await SecureStore.getItemAsync(PUSH_OPTED_USER_KEY)) !== userId) {
    return "disabled";
  }
  const savedToken = await currentToken();
  if (!savedToken) return "disabled";
  try {
    const { installationId } = await installationIdentity();
    const response = await api.get<{ registered: boolean }>(
      "/notifications/push-status",
      { params: { installation_id: installationId } }
    );
    return response.data.registered ? "enabled" : "disabled";
  } catch {
    return "disabled";
  }
}

async function enableForUser(userId: string): Promise<void> {
  if (Platform.OS === "web" || !Device.isDevice) {
    throw new Error("Push notifications require a physical device.");
  }
  let permission = await Notifications.getPermissionsAsync();
  if (permission.status !== "granted") {
    permission = await Notifications.requestPermissionsAsync();
  }
  if (permission.status !== "granted") {
    throw new Error("Notification permission was not granted.");
  }
  await registerToken(userId);
}

export function enablePushNotifications(userId: string): Promise<void> {
  return serialize(() => enableForUser(userId));
}

async function initializeForUser(userId: string): Promise<void> {
  if (Platform.OS === "web" || !Device.isDevice) return;
  if ((await SecureStore.getItemAsync(PUSH_OPTED_USER_KEY)) !== userId) return;
  const permission = await Notifications.getPermissionsAsync();
  if (permission.status === "granted") await registerToken(userId);
}

export function initializePushNotifications(userId: string): Promise<void> {
  return serialize(() => initializeForUser(userId));
}

async function unregisterInstallation(): Promise<void> {
  await SecureStore.deleteItemAsync(PUSH_OPTED_USER_KEY);
  const installationId = await SecureStore.getItemAsync(PUSH_INSTALLATION_KEY);
  const unregisterSecret = await SecureStore.getItemAsync(
    PUSH_UNREGISTER_SECRET_KEY
  );
  if (!installationId || !unregisterSecret) {
    await SecureStore.deleteItemAsync(PUSH_TOKEN_KEY);
    await SecureStore.deleteItemAsync(PUSH_UNREGISTER_PENDING_KEY);
    return;
  }
  try {
    await api.delete("/notifications/push-device", {
      data: {
        installation_id: installationId,
        unregister_secret: unregisterSecret,
      },
    });
    await SecureStore.deleteItemAsync(PUSH_TOKEN_KEY);
    await SecureStore.deleteItemAsync(PUSH_UNREGISTER_PENDING_KEY);
  } catch (error) {
    await SecureStore.setItemAsync(PUSH_UNREGISTER_PENDING_KEY, "true");
    throw error;
  }
}

export function unregisterPushNotifications(): Promise<void> {
  return serialize(unregisterInstallation);
}

async function retryPendingUnregisterInternal(): Promise<void> {
  if (
    Platform.OS === "web" ||
    (await SecureStore.getItemAsync(PUSH_UNREGISTER_PENDING_KEY)) !== "true"
  ) {
    return;
  }
  await unregisterInstallation();
}

export function retryPendingPushUnregister(): Promise<void> {
  return serialize(retryPendingUnregisterInternal);
}

export function installPushResponseListener(): () => void {
  if (Platform.OS === "web") return () => {};
  const subscription = Notifications.addNotificationResponseReceivedListener(
    (response) => {
      const route = response.notification.request.content.data?.route;
      if (typeof route === "string" && route.startsWith("/")) {
        router.push(route as Href);
      }
    }
  );
  return () => subscription.remove();
}

export async function routeLastPushResponse(): Promise<void> {
  if (Platform.OS === "web") return;
  const response = await Notifications.getLastNotificationResponseAsync();
  const route = response?.notification.request.content.data?.route;
  if (typeof route === "string" && route.startsWith("/")) {
    router.push(route as Href);
    await Notifications.clearLastNotificationResponseAsync();
  }
}