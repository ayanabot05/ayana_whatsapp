import { createContext, useContext, useEffect, useState, useCallback, useRef } from "react";
import { api } from "../lib/api";
import { setSentryUser, clearSentryUser } from "../lib/sentryUser";

const AuthContext = createContext(null);
const INACTIVITY_TIMEOUT_MS = 5 * 60 * 1000; // 5 minutes

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null); // null = checking, false = logged out
  const [config, setConfig] = useState(null);
  const inactivityTimerRef = useRef(null);

  const logout = useCallback(async () => {
    try { await api.post("/auth/logout"); } catch {}
    setUser(false);
    clearSentryUser();
  }, []);

  const refreshAccessToken = useCallback(async () => {
    try {
      const { data } = await api.post("/auth/refresh", {});
      if (data.user) {
        setUser(data.user);
        setSentryUser(data.user);
      }
      return true;
    } catch {
      setUser(false);
      clearSentryUser();
      return false;
    }
  }, []);

  const refreshUser = useCallback(async () => {
    try {
      const { data } = await api.get("/auth/me");
      setUser(data);
      setSentryUser(data);
    } catch {
      const refreshed = await refreshAccessToken();
      if (!refreshed) return;
      try {
        const { data } = await api.get("/auth/me");
        setUser(data);
        setSentryUser(data);
      } catch {
        setUser(false);
        clearSentryUser();
      }
    }
  }, [refreshAccessToken]);

  // Inactivity auto-logout
  useEffect(() => {
    if (!user) return;
    const resetInactivityTimer = () => {
      if (inactivityTimerRef.current) clearTimeout(inactivityTimerRef.current);
      inactivityTimerRef.current = setTimeout(() => logout(), INACTIVITY_TIMEOUT_MS);
    };
    const activityEvents = ["mousemove", "keydown", "click", "scroll", "touchstart"];
    activityEvents.forEach((evt) => window.addEventListener(evt, resetInactivityTimer));
    resetInactivityTimer();
    return () => {
      if (inactivityTimerRef.current) clearTimeout(inactivityTimerRef.current);
      activityEvents.forEach((evt) => window.removeEventListener(evt, resetInactivityTimer));
    };
  }, [user, logout]);

  useEffect(() => {
    refreshUser();
    let cancelled = false;
    const loadConfig = async (attempt = 0) => {
      try {
        const { data } = await api.get("/config");
        if (!cancelled) setConfig(data);
      } catch {
        if (!cancelled && attempt < 6) {
          setTimeout(() => loadConfig(attempt + 1), 700 * (attempt + 1));
        }
      }
    };
    loadConfig();
    return () => { cancelled = true; };
  }, [refreshUser]);

  const loginWithToken = (_accessToken, _refreshToken, userData) => {
    setUser(userData);
    setSentryUser(userData);
  };

  return (
    <AuthContext.Provider value={{ user, setUser, config, refreshUser, loginWithToken, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export const useAuth = () => useContext(AuthContext);