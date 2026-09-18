/**
 * Centralised streaming-provider display-name helpers.
 *
 * The backend/TMDB provider ids and raw names don't always match the label we
 * want to show to users. In particular:
 *   - "now_tv" / "Now TV" should display as "NOW",
 *   - any BBC iPlayer variant should display as "BBC iPlayer".
 * Everything else falls back to a prettified id or the raw service name.
 */

/** Prettify a snake_case provider id, e.g. "prime_video" -> "Prime Video". */
export function prettifyProviderId(id: string): string {
  return id
    .split("_")
    .map((s) => (s ? s[0].toUpperCase() + s.slice(1) : s))
    .join(" ");
}

/**
 * Resolve the display name for a provider given its id and/or raw name.
 * Applies brand-specific overrides (NOW, BBC iPlayer) then falls back to the
 * raw name or a prettified id.
 */
export function providerDisplayName(
  serviceId?: string | null,
  rawName?: string | null
): string {
  const idKey = (serviceId || "").toLowerCase().replace(/[\s_-]/g, "");
  const nameKey = (rawName || "").toLowerCase().replace(/[\s_-]/g, "");

  // NOW TV → "NOW"
  if (idKey === "nowtv" || idKey === "now" || nameKey === "nowtv" || nameKey === "now") {
    return "NOW";
  }

  // Any BBC iPlayer variant → "BBC iPlayer"
  if (idKey.includes("bbciplayer") || idKey.includes("iplayer") || nameKey.includes("iplayer")) {
    return "BBC iPlayer";
  }

  if (rawName && rawName.trim()) return rawName;
  if (serviceId) return prettifyProviderId(serviceId);
  return "";
}
