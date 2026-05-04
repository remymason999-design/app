import axios from "axios";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
export const API = `${BACKEND_URL}/api`;

const api = axios.create({
    baseURL: API,
    withCredentials: true,
});

export const apiGet = (url, config) => api.get(url, config).then((r) => r.data);
export const apiPost = (url, data, config) => api.post(url, data, config).then((r) => r.data);
export const apiPut = (url, data, config) => api.put(url, data, config).then((r) => r.data);

export function formatApiError(detail) {
    if (detail == null) return "Something went wrong. Please try again.";
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail))
        return detail.map((e) => (e?.msg ? e.msg : JSON.stringify(e))).join(" ");
    if (detail?.msg) return detail.msg;
    return String(detail);
}

export default api;
