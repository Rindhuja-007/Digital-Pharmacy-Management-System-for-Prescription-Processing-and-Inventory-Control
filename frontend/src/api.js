import axios from "axios";

export const TOKEN_KEY = "pharmacare_token";

const api = axios.create({ baseURL: import.meta.env.VITE_API_URL || "http://localhost:8000" });

// Attach the Bearer token to every request.
api.interceptors.request.use((config) => {
  const token = localStorage.getItem(TOKEN_KEY);
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

// On 401 (expired/invalid token) log out — but not for a failed login attempt itself.
let onUnauthorized = () => {};
export const setUnauthorizedHandler = (fn) => { onUnauthorized = fn; };

api.interceptors.response.use(
  (res) => res,
  (err) => {
    const url = err.config?.url || "";
    if (err.response?.status === 401 && !url.startsWith("/auth/login") && !url.startsWith("/auth/token")) {
      onUnauthorized();
    }
    return Promise.reject(err);
  }
);

/** Turn any axios/FastAPI error into a sentence the user can act on. */
export function errorMessage(err) {
  const data = err?.response?.data;
  if (!err?.response) return "Cannot reach the server. Check that the API is running.";
  if (data?.message) return data.message;
  if (typeof data?.detail === "string") return data.detail;
  if (Array.isArray(data?.detail)) return data.detail.map((d) => d.msg).join("; ");
  return `Request failed (${err.response.status})`;
}

export default api;
