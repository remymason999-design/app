import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { AppState } from "react-native";
import {
  AppleLoginPayload,
  WsUser,
  appleLoginRequest,
  fetchMe,
  hasSession,
  loadTokens,
  loginRequest,
  linkAppleRequest,
  logoutRequest,
  registerRequest,
} from "@/lib/api";
import { queryClient } from "@/lib/query-client";
import { unregisterPushNotifications } from "@/lib/push-notifications";
import { analytics, EVENTS } from "@/lib/analytics";
import { captureLogoutAndReset } from "@/lib/analytics-flow";

interface AuthState {
  user: WsUser | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<WsUser>;
  loginWithApple: (payload: AppleLoginPayload) => Promise<WsUser>;
  loginAndLinkApple: (
    email: string,
    password: string,
    payload: AppleLoginPayload
  ) => Promise<WsUser>;
  register: (name: string, email: string, password: string) => Promise<WsUser>;
  logout: () => Promise<void>;
  refresh: () => Promise<void>;
  setUser: React.Dispatch<React.SetStateAction<WsUser | null>>;
}

const AuthContext = createContext<AuthState | undefined>(undefined);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<WsUser | null>(null);
  const [loading, setLoading] = useState(true);
  const recoveringSession = useRef(false);
  const analyticsUserId = useRef<string | null>(null);

  useEffect(() => {
    const id = user?.user_id ? String(user.user_id) : null;
    if (id === analyticsUserId.current) return;
    analyticsUserId.current = id;
    if (user && id) analytics.switchIdentity(user);
  }, [user]);

  const recoverSession = useCallback(async (): Promise<boolean> => {
    if (recoveringSession.current || !hasSession()) return false;
    recoveringSession.current = true;
    try {
      const me = await fetchMe();
      setUser(me);
      return true;
    } catch {
      // Keep the stored refresh token. A foreground/interval retry will recover
      // after a temporary backend or network outage.
      return false;
    } finally {
      recoveringSession.current = false;
    }
  }, []);

  // Persistent login: restore tokens from secure storage, then validate.
  useEffect(() => {
    (async () => {
      try {
        await loadTokens();
        if (hasSession()) {
          for (let attempt = 0; attempt < 3; attempt += 1) {
            const recovered = await recoverSession();
            if (recovered || !hasSession()) break;
            if (attempt < 2) {
              await new Promise((resolve) => setTimeout(resolve, 500 * 2 ** attempt));
            }
          }
        }
      } catch {
        setUser(null);
      } finally {
        setLoading(false);
      }
    })();
  }, [recoverSession]);

  useEffect(() => {
    const timer = setInterval(() => {
      if (!user && hasSession()) void recoverSession();
    }, 10000);
    const subscription = AppState.addEventListener("change", (state) => {
      if (state === "active" && !user && hasSession()) void recoverSession();
    });
    return () => {
      clearInterval(timer);
      subscription.remove();
    };
  }, [recoverSession, user]);

  const login = useCallback(async (email: string, password: string) => {
    const u = await loginRequest(email, password);
    queryClient.clear();
    analytics.switchIdentity(u);
    analyticsUserId.current = String(u.user_id);
    setUser(u);
    analytics.capture(EVENTS.LOGIN, { method: "password" }, { user: u, allowDuplicate: true });
    return u;
  }, []);

  const loginWithApple = useCallback(async (payload: AppleLoginPayload) => {
    const u = await appleLoginRequest(payload);
    queryClient.clear();
    analytics.switchIdentity(u);
    analyticsUserId.current = String(u.user_id);
    setUser(u);
    analytics.capture(EVENTS.LOGIN, { method: "apple" }, { user: u, allowDuplicate: true });
    return u;
  }, []);

  const loginAndLinkApple = useCallback(
    async (email: string, password: string, payload: AppleLoginPayload) => {
      const u = await loginRequest(email, password);
      try {
        await linkAppleRequest(payload);
      } catch (error) {
        await logoutRequest();
        throw error;
      }
      queryClient.clear();
      analytics.switchIdentity(u);
      analyticsUserId.current = String(u.user_id);
      setUser(u);
      analytics.capture(EVENTS.LOGIN, { method: "apple_linked" }, { user: u, allowDuplicate: true });
      return u;
    },
    []
  );

  const register = useCallback(async (name: string, email: string, password: string) => {
    const u = await registerRequest(name, email, password);
    queryClient.clear();
    analytics.switchIdentity(u);
    analyticsUserId.current = String(u.user_id);
    setUser(u);
    analytics.capture(EVENTS.ACCOUNT_CREATED, { method: "password" }, { user: u, allowDuplicate: true });
    return u;
  }, []);

  const logout = useCallback(async () => {
    try {
      await unregisterPushNotifications();
    } catch {
      // Signing out must still succeed if device deregistration is unavailable.
    }
    await logoutRequest();
    captureLogoutAndReset(analytics, user);
    analyticsUserId.current = null;
    setUser(null);
    queryClient.clear();
  }, [user]);

  const refresh = useCallback(async () => {
    try {
      const me = await fetchMe();
      setUser(me);
    } catch {
      // keep existing user on transient failures
    }
  }, []);

  const value = useMemo(
    () => ({
      user,
      loading,
      login,
      loginWithApple,
      loginAndLinkApple,
      register,
      logout,
      refresh,
      setUser,
    }),
    [user, loading, login, loginWithApple, loginAndLinkApple, register, logout, refresh]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside AuthProvider");
  return ctx;
}
