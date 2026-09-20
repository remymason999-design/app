import { QueryClient, QueryFunctionContext } from "@tanstack/react-query";
import { api } from "@/lib/api";

/**
 * Default fetcher: query keys are API paths, e.g. ['/watchlist'] or
 * ['/movies', id]. Segments are joined into the request path.
 */
async function defaultQueryFn({ queryKey }: QueryFunctionContext) {
  const path = queryKey.filter((s) => typeof s === "string" || typeof s === "number").join("/");
  const r = await api.get(path.startsWith("/") ? path : `/${path}`);
  return r.data;
}

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      queryFn: defaultQueryFn,
      staleTime: 60_000,
      retry: 1,
    },
  },
});
