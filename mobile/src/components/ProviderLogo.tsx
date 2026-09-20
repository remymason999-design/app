/**
 * ProviderLogo — single source of truth for ALL provider logo rendering in the
 * native app. Mirrors the web app's frontend/src/components/ProviderLogo.jsx
 * central map.
 *
 * Every subscription streaming service renders its real TMDB logo image
 * (via expo-image, rounded). The brand-coloured lettermark fallback only fires
 * when the image is missing or fails to load — matching the web behaviour.
 *
 * Logo paths are hardcoded (verified against TMDB's GB provider list) exactly
 * like the web map — every mapped service, UK ones included, renders a real
 * logo image; the lettermark only fires when the image fails to load.
 */
import { Image } from "expo-image";
import { useState } from "react";
import { StyleSheet, Text, View } from "react-native";

import { providerDisplayName } from "@/lib/providers";

const TMDB_IMG = "https://image.tmdb.org/t/p/w185";

export interface ProviderMeta {
  bg: string;
  fg: string;
  mark: string;
  name: string;
  /** Full TMDB logo URL, or undefined when no logo exists (lettermark only). */
  logo?: string;
}

/** Subscription streaming service map — keyed by service ID. */
export const PROVIDERS: Record<string, ProviderMeta> = {
  netflix: {
    bg: "#E50914", fg: "#fff", mark: "N", name: "Netflix",
    logo: `${TMDB_IMG}/pbpMk2JmcoNnQwx5JGpXngfoWtp.jpg`,
  },
  disney_plus: {
    bg: "#0E47A1", fg: "#fff", mark: "D+", name: "Disney+",
    logo: `${TMDB_IMG}/97yvRBw1GzX7fXprcF80er19ot.jpg`,
  },
  hbo_max: {
    bg: "#002BE7", fg: "#fff", mark: "max", name: "Max",
    logo: `${TMDB_IMG}/jbe4gVSfRlbPTdESXhEKpornsfu.jpg`,
  },
  prime_video: {
    bg: "#00A8E1", fg: "#fff", mark: "prime", name: "Prime Video",
    logo: `${TMDB_IMG}/pvske1MyAoymrs5bguRfVqYiM9a.jpg`,
  },
  apple_tv: {
    bg: "#1C1C1E", fg: "#fff", mark: "TV+", name: "Apple TV+",
    logo: `${TMDB_IMG}/mcbz1LgtErU9p4UdbZ0rG6RTWHX.jpg`,
  },
  hulu: {
    bg: "#1CE783", fg: "#000", mark: "hulu", name: "Hulu",
    logo: `${TMDB_IMG}/bxBlRPEPpMVDc4jMhSrTf2339DW.jpg`,
  },
  paramount: {
    bg: "#0064FF", fg: "#fff", mark: "P+", name: "Paramount+",
    logo: `${TMDB_IMG}/h5DcR0J2EESLitnhR8xLG1QymTE.jpg`,
  },
  peacock: {
    bg: "#FA6400", fg: "#fff", mark: "P", name: "Peacock",
    logo: `${TMDB_IMG}/2aGrp1xw3qhwCYvNGAJZPdjfeeX.jpg`,
  },
  // UK services — real TMDB logos (same paths as the web ProviderLogo map).
  // Lettermark only fires if the image fails to load.
  itvx: {
    bg: "#102C3D", fg: "#fff", mark: "ITVX", name: "ITVX",
    logo: `${TMDB_IMG}/1LuvKw01c2KQCt6DqgAgR06H2pT.jpg`,
  },
  now_tv: {
    bg: "#001B33", fg: "#00D6A4", mark: "NOW", name: "NOW",
    logo: `${TMDB_IMG}/g0E9h3JAeIwmdvxlT73jiEuxdNj.jpg`,
  },
  channel_4: {
    bg: "#1B1B1B", fg: "#fff", mark: "4", name: "Channel 4",
    logo: `${TMDB_IMG}/uMWCgjsGnO5IoQtqxXOjnQA5gt9.jpg`,
  },
  discovery_plus: {
    bg: "#1A2B6D", fg: "#fff", mark: "d+", name: "discovery+",
    logo: `${TMDB_IMG}/bPW3J8KlLrot95sLzadnpzVe61f.jpg`,
  },
  bbc_iplayer: {
    bg: "#000000", fg: "#FF4C98", mark: "iP", name: "BBC iPlayer",
    logo: `${TMDB_IMG}/nc8Tpsr8SqCbsTUogPDD06gGzB3.jpg`,
  },
  mubi: {
    bg: "#000000", fg: "#fff", mark: "M", name: "MUBI",
    logo: `${TMDB_IMG}/x570VpH2C9EKDf1riP83rYc5dnL.jpg`,
  },
};

/** Deterministic colour from a string — last-resort fallback. */
function hashColor(str: string): string {
  let h = 0;
  for (let i = 0; i < str.length; i++) h = (h * 31 + str.charCodeAt(i)) & 0xffffff;
  return `#${h.toString(16).padStart(6, "0")}`;
}

/**
 * Resolve any service id to provider metadata, falling back to a deterministic
 * colour + first-letter lettermark for unknown services.
 */
export function resolveProvider(sid?: string | null, rawName?: string | null): ProviderMeta {
  const key = (sid || "").toLowerCase();
  if (PROVIDERS[key]) return PROVIDERS[key];
  const name = providerDisplayName(sid, rawName) || sid || "?";
  return {
    bg: hashColor(name),
    fg: "#fff",
    mark: (name[0] || "?").toUpperCase(),
    name,
  };
}

interface Props {
  /** Service ID ("netflix", "hbo_max", …). */
  sid?: string | null;
  /** Optional raw name for unknown services (used by lettermark fallback). */
  name?: string | null;
  /**
   * Optional explicit logo URL (e.g. from the API). When provided and the
   * service isn't in the map, it takes precedence over the lettermark.
   */
  logoUrl?: string | null;
  /** Square size in px (default 40). */
  size?: number;
  /** Corner radius (default size * 0.28 for a rounded-square look). */
  radius?: number;
}

/**
 * ProviderLogo — subscription streaming service badge.
 *
 * Renders the TMDB logo image with a brand-coloured lettermark fallback on
 * missing/error, matching the web ProviderLogo component.
 */
export function ProviderLogo({ sid, name, logoUrl, size = 40, radius }: Props) {
  const [imgError, setImgError] = useState(false);
  const meta = resolveProvider(sid, name);
  const logo = meta.logo ?? logoUrl ?? undefined;
  const borderRadius = radius ?? Math.round(size * 0.28);
  const showImage = !!logo && !imgError;

  return (
    <View
      style={[
        styles.badge,
        { width: size, height: size, borderRadius, backgroundColor: meta.bg },
      ]}
      accessible
      accessibilityLabel={meta.name}
    >
      {showImage ? (
        <Image
          source={{ uri: logo }}
          style={{ width: size, height: size, borderRadius }}
          contentFit="cover"
          transition={150}
          onError={() => setImgError(true)}
        />
      ) : (
        <Text
          style={[
            styles.mark,
            { color: meta.fg, fontSize: Math.max(10, Math.round(size * 0.34)) },
          ]}
          numberOfLines={1}
        >
          {meta.mark}
        </Text>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  badge: {
    overflow: "hidden",
    alignItems: "center",
    justifyContent: "center",
  },
  mark: {
    fontFamily: "Inter_800ExtraBold",
    textAlign: "center",
    lineHeight: undefined,
    paddingHorizontal: 2,
  },
});
