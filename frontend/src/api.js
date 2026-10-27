import axios from "axios";

export const api = axios.create({ baseURL: import.meta.env.VITE_API_URL || "http://localhost:8000" });

api.interceptors.request.use((cfg) => {
  const t = localStorage.getItem("token");
  if (t) cfg.headers.Authorization = `Bearer ${t}`;
  return cfg;
});

api.interceptors.response.use(
  (r) => r,
  (err) => {
    if (err.response?.status === 401 && !err.config.url.includes("/auth/login")) {
      localStorage.clear();
      window.location.href = "/login";
    }
    return Promise.reject(err);
  }
);

export const errMsg = (e) => e.response?.data?.detail || "Something went wrong.";
export const getUser = () => JSON.parse(localStorage.getItem("user") || "null");
export const isStaff = (u) => u && u.role !== "customer";
export const date = (s) => (s ? new Date(s + (s.endsWith("Z") ? "" : "Z")).toLocaleString() : "-");
