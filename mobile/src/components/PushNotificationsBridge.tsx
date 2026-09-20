import { useEffect } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { AppState } from "react-native";

import { useAuth } from "@/context/AuthContext";
import {
  initializePushNotifications,
  installPushResponseListener,
  retryPendingPushUnregister,
  routeLastPushResponse,
} from "@/lib/push-notifications";

export function PushNotificationsBridge() {
  const { user } = useAuth();
  const queryClient = useQueryClient();

  useEffect(() => installPushResponseListener(), []);

  const userId = user?.user_id;

  useEffect(() => {
    void retryPendingPushUnregister()
      .catch(() => undefined)
      .then(() => {
        if (userId) {
          void routeLastPushResponse().catch(() => undefined);
          return initializePushNotifications(userId);
        }
      })
      .catch(() => undefined);
  }, [userId]);

  useEffect(() => {
    const subscription = AppState.addEventListener("change", (state) => {
      if (state === "active" && userId) {
        void queryClient.invalidateQueries({ refetchType: "active" });
        void retryPendingPushUnregister()
          .catch(() => undefined)
          .then(() => initializePushNotifications(userId))
          .catch(() => undefined);
      }
    });
    return () => subscription.remove();
  }, [queryClient, userId]);

  return null;
}