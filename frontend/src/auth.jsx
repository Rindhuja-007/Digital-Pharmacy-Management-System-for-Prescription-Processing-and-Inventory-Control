import { createContext, useCallback, useContext, useEffect, useState } from "react";
import api, { TOKEN_KEY, setUnauthorizedHandler } from "./api";

const AuthContext = createContext(null);
export const useAuth = () => useContext(AuthContext);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(!!localStorage.getItem(TOKEN_KEY));
  const [notice, setNotice] = useState("");

  const logout = useCallback((message = "") => {
    localStorage.removeItem(TOKEN_KEY);
    setUser(null);
    setNotice(message);
  }, []);

  useEffect(() => {
    setUnauthorizedHandler(() => logout("Your session has expired. Please sign in again."));
    if (!localStorage.getItem(TOKEN_KEY)) return;
    api.get("/auth/me").then((r) => setUser(r.data)).catch(() => logout()).finally(() => setLoading(false));
  }, [logout]);

  const login = async (username, password) => {
    const { data } = await api.post("/auth/login", { username, password });
    localStorage.setItem(TOKEN_KEY, data.access_token);
    setNotice("");
    setUser(data.user);
  };

  return (
    <AuthContext.Provider value={{ user, loading, login, logout: () => logout(), notice, isAdmin: user?.role === "ADMIN" }}>
      {children}
    </AuthContext.Provider>
  );
}
