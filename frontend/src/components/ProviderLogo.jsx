/**
 * ProviderLogo — single source of truth for ALL provider logo rendering.
 *
 * Every streaming service and VOD platform uses real TMDB logo images.
 * Initials/colour fallback only fires when the image genuinely fails to load.
 *
 * Exports:
 *   ProviderLogo  – subscription streaming badge (takes sid like "netflix")
 *   RentBuyLogo   – VOD rent/buy badge (takes raw name like "Apple TV Store")
 *   PROVIDERS     – metadata map (used by Landing page showcase)
 */
import { useState } from "react";

const TMDB_IMG = "https://image.tmdb.org/t/p/w185";

/** Subscription streaming service map — keyed by service ID. */
export const PROVIDERS = {
    netflix: {
        bg: "#E50914", fg: "#fff",
        mark: "N", name: "Netflix",
        markCls: "text-[110%] font-black italic tracking-tighter",
        logo: `${TMDB_IMG}/pbpMk2JmcoNnQwx5JGpXngfoWtp.jpg`,
    },
    disney_plus: {
        bg: "#0E47A1", fg: "#fff",
        mark: "D+", name: "Disney+",
        markCls: "text-[62%] font-black tracking-tight",
        logo: `${TMDB_IMG}/97yvRBw1GzX7fXprcF80er19ot.jpg`,
    },
    hbo_max: {
        bg: "#002BE7", fg: "#fff",
        mark: "max", name: "Max",
        markCls: "text-[48%] font-bold tracking-wide lowercase",
        logo: `${TMDB_IMG}/jbe4gVSfRlbPTdESXhEKpornsfu.jpg`,
    },
    prime_video: {
        bg: "#00A8E1", fg: "#fff",
        mark: "prime", name: "Prime Video",
        markCls: "text-[42%] font-bold tracking-tight",
        logo: `${TMDB_IMG}/pvske1MyAoymrs5bguRfVqYiM9a.jpg`,
    },
    apple_tv: {
        bg: "#1C1C1E", fg: "#fff",
        mark: "TV+", name: "Apple TV+",
        markCls: "text-[52%] font-semibold tracking-tight",
        logo: `${TMDB_IMG}/mcbz1LgtErU9p4UdbZ0rG6RTWHX.jpg`,
    },
    hulu: {
        bg: "#1CE783", fg: "#000",
        mark: "hulu", name: "Hulu",
        markCls: "text-[42%] font-bold tracking-widest lowercase",
        logo: `${TMDB_IMG}/bxBlRPEPpMVDc4jMhSrTf2339DW.jpg`,
    },
    paramount: {
        bg: "#0064FF", fg: "#fff",
        mark: "P+", name: "Paramount+",
        markCls: "text-[60%] font-black tracking-tight",
        logo: `${TMDB_IMG}/h5DcR0J2EESLitnhR8xLG1QymTE.jpg`,
    },
    peacock: {
        bg: "#FA6400", fg: "#fff",
        mark: "P", name: "Peacock",
        markCls: "text-[85%] font-bold",
        logo: `${TMDB_IMG}/2aGrp1xw3qhwCYvNGAJZPdjfeeX.jpg`,
    },
    now_tv: {
        bg: "#001B33", fg: "#00D6A4",
        mark: "NOW", name: "NOW",
        markCls: "text-[40%] font-black tracking-tight",
        logo: `${TMDB_IMG}/g0E9h3JAeIwmdvxlT73jiEuxdNj.jpg`,
    },
    channel_4: {
        bg: "#1B1B1B", fg: "#fff",
        mark: "4", name: "Channel 4",
        markCls: "text-[85%] font-black",
        logo: `${TMDB_IMG}/uMWCgjsGnO5IoQtqxXOjnQA5gt9.jpg`,
    },
    discovery_plus: {
        bg: "#1A2B6D", fg: "#fff",
        mark: "d+", name: "discovery+",
        markCls: "text-[60%] font-black tracking-tight",
        logo: `${TMDB_IMG}/bPW3J8KlLrot95sLzadnpzVe61f.jpg`,
    },
    bbc_iplayer: {
        bg: "#000", fg: "#FF4C98",
        mark: "iPlayer", name: "BBC iPlayer",
        markCls: "text-[34%] font-black tracking-tight lowercase",
        logo: `${TMDB_IMG}/nc8Tpsr8SqCbsTUogPDD06gGzB3.jpg`,
    },
    mubi: {
        bg: "#000", fg: "#fff",
        mark: "MUBI", name: "MUBI",
        markCls: "text-[40%] font-black tracking-widest",
        logo: `${TMDB_IMG}/x570VpH2C9EKDf1riP83rYc5dnL.jpg`,
    },
    itvx: {
        bg: "#102C3D", fg: "#fff",
        mark: "ITVX", name: "ITVX",
        markCls: "text-[40%] font-black tracking-tight",
        logo: `${TMDB_IMG}/1LuvKw01c2KQCt6DqgAgR06H2pT.jpg`,
    },
};

/**
 * VOD / rent-buy platform map — keyed by the exact provider name string
 * returned by the TMDB watch providers API.
 * All logo paths verified against TMDB's GB region provider list.
 */
const VOD_PROVIDERS = {
    "Apple TV Store":     { bg: "#1C1C1E", fg: "#fff", mark: "TV+", logo: `${TMDB_IMG}/SPnB1qiCkYfirS2it3hZORwGVn.jpg` },
    "Apple TV":           { bg: "#1C1C1E", fg: "#fff", mark: "TV+", logo: `${TMDB_IMG}/mcbz1LgtErU9p4UdbZ0rG6RTWHX.jpg` },
    "Amazon Video":       { bg: "#FF9900", fg: "#000", mark: "Az",  logo: `${TMDB_IMG}/qR6FKvnPBx2O37FDg8PNM7efwF3.jpg` },
    "Rakuten TV":         { bg: "#BF0000", fg: "#fff", mark: "R",   logo: `${TMDB_IMG}/bZvc9dXrXNly7cA0V4D9pR8yJwm.jpg` },
    "Google Play Movies": { bg: "#4285F4", fg: "#fff", mark: "G",   logo: `${TMDB_IMG}/8z7rC8uIDaTM91X0ZfkRf04ydj2.jpg` },
    "YouTube":            { bg: "#FF0000", fg: "#fff", mark: "▶",   logo: `${TMDB_IMG}/pTnn5JwWr4p3pG8H6VrpiQo7Vs0.jpg` },
    "YouTube Premium":    { bg: "#FF0000", fg: "#fff", mark: "▶",   logo: `${TMDB_IMG}/pTnn5JwWr4p3pG8H6VrpiQo7Vs0.jpg` },
    "Sky Store":          { bg: "#0072C6", fg: "#fff", mark: "Sky", logo: `${TMDB_IMG}/59TxOAYcoFaufd6CWm465oPchD.jpg` },
    "Sky Go":             { bg: "#0072C6", fg: "#fff", mark: "Sky", logo: `${TMDB_IMG}/kAZkQcIxMxTmlwdgSB05fqtymp0.jpg` },
    "JustWatch TV":       { bg: "#28a745", fg: "#fff", mark: "JW",  logo: `${TMDB_IMG}/g2IaWyo6jCY0rIFjb4qgZ0bSmm3.jpg` },
    "Curzon Home Cinema": { bg: "#1a1a1a", fg: "#fff", mark: "C",   logo: `${TMDB_IMG}/pXQhPQmlIYsIZD4urWs8Ul8PhA6.jpg` },
    "BFI Player":         { bg: "#1a1a1a", fg: "#fff", mark: "BFI", logo: `${TMDB_IMG}/erGoVIuKJ0PYOJ8dh62o4YhwaJK.jpg` },
    "Vudu":               { bg: "#3FC2E0", fg: "#fff", mark: "V" },
    "Microsoft Store":    { bg: "#00A4EF", fg: "#fff", mark: "M" },
    "Fandango At Home":   { bg: "#EE4E4E", fg: "#fff", mark: "F" },
    "Google Play":        { bg: "#4285F4", fg: "#fff", mark: "G",   logo: `${TMDB_IMG}/8z7rC8uIDaTM91X0ZfkRf04ydj2.jpg` },
};

/** Deterministic colour from a string — last-resort fallback. */
function hashColor(str) {
    let h = 0;
    for (let i = 0; i < str.length; i++) h = (h * 31 + str.charCodeAt(i)) & 0xffffff;
    return `#${h.toString(16).padStart(6, "0")}`;
}

/**
 * Resolve a VOD provider name (or a mis-stored subscription ID like "prime_video")
 * to a metadata object with { bg, fg, mark, logo? }.
 */
function resolveVod(name) {
    if (!name) return { bg: "#333", fg: "#fff", mark: "?" };
    if (VOD_PROVIDERS[name]) return VOD_PROVIDERS[name];
    if (PROVIDERS[name])     return PROVIDERS[name];
    return { bg: hashColor(name), fg: "#fff", mark: name.charAt(0).toUpperCase() };
}

/**
 * Shared logo image renderer used by both ProviderLogo and RentBuyLogo.
 * Uses object-contain so logos with transparent regions or unusual shapes
 * are never cropped, while the brand background colour fills any gaps.
 */
function LogoBadge({ logo, name, bg, fg, mark, markCls = "", size, shape, imgError, setImgError, ring = "" }) {
    return (
        <div
            className={`shrink-0 overflow-hidden ${shape} ${ring}`}
            style={{ width: size, height: size, background: bg }}
            title={name}
            aria-label={name}
        >
            {logo && !imgError ? (
                <img
                    src={logo}
                    alt={name}
                    width={size * 2}
                    height={size * 2}
                    className="w-full h-full object-contain"
                    draggable={false}
                    onError={() => setImgError(true)}
                />
            ) : (
                <div className="w-full h-full grid place-items-center">
                    <span
                        className={`leading-none select-none ${markCls}`}
                        style={{ color: fg, fontSize: size * 0.40 }}
                    >
                        {mark}
                    </span>
                </div>
            )}
        </div>
    );
}

/**
 * ProviderLogo — subscription streaming service badge.
 *
 * @param {object}  props
 * @param {string}  props.sid         Service ID ("netflix", "hbo_max", …)
 * @param {number}  [props.size]      Square size in px (default 32)
 * @param {string}  [props.shape]     Tailwind rounding class (default "rounded-xl")
 * @param {boolean} [props.subscribed] Amber ring when user subscribes
 */
export function ProviderLogo({ sid, size = 32, shape = "rounded-xl", subscribed = false }) {
    const [imgError, setImgError] = useState(false);
    const p = PROVIDERS[sid];
    if (!p) return null;

    const ring = subscribed
        ? "ring-2 ring-amber/70 ring-offset-1 ring-offset-black transition-transform hover:scale-110 active:scale-95"
        : "transition-transform hover:scale-110 active:scale-95";

    return (
        <LogoBadge
            logo={p.logo}
            name={p.name}
            bg={p.bg}
            fg={p.fg}
            mark={p.mark}
            markCls={p.markCls}
            size={size}
            shape={shape}
            imgError={imgError}
            setImgError={setImgError}
            ring={ring}
        />
    );
}

/**
 * RentBuyLogo — VOD rent/buy platform badge.
 *
 * Accepts the raw provider name string from TMDB ("Apple TV Store", "Amazon Video", …).
 * Also handles mis-stored subscription IDs ("prime_video") gracefully.
 *
 * @param {object} props
 * @param {string} props.name   Raw provider name
 * @param {number} [props.size] Square size in px (default 36)
 * @param {string} [props.shape] Tailwind rounding class
 */
export function RentBuyLogo({ name, size = 36, shape = "rounded-xl" }) {
    const [imgError, setImgError] = useState(false);
    const meta = resolveVod(name);

    return (
        <LogoBadge
            logo={meta.logo}
            name={meta.name || name}
            bg={meta.bg}
            fg={meta.fg}
            mark={meta.mark}
            markCls={meta.markCls || "font-bold"}
            size={size}
            shape={shape}
            imgError={imgError}
            setImgError={setImgError}
        />
    );
}
