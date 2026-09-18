/**
 * WatchSmart brand assets.
 *
 * <Mark />  — the WatchSmart brand mark (two overlapping cards forming a "W"
 *             with a play button), rendered from the official transparent PNG.
 * <Logo />  — the mark + "Watch" (white) / "Smart" (orange) wordmark, with an
 *             optional tagline and a stacked variant for the Welcome screen.
 */

const MARK_SRC = "/brand/watchsmart-mark-trim.png";

export function Mark({ size = 40, className = "" }) {
    return (
        <img
            src={MARK_SRC}
            alt="WatchSmart"
            draggable="false"
            className={`select-none ${className}`}
            style={{ height: size, width: "auto", objectFit: "contain" }}
        />
    );
}

export default function Logo({
    size = 36,
    showMark = true,
    stacked = false,
    tagline = false,
    className = "",
    textClassName = "",
}) {
    if (stacked) {
        return (
            <div className={`flex flex-col items-center gap-4 ${className}`}>
                {showMark && <Mark size={size} />}
                <div className="flex flex-col items-center gap-1.5">
                    <span className={`font-display tracking-tight leading-none ${textClassName}`} style={{ fontSize: size * 0.42 }}>
                        <span className="text-white">Watch</span>
                        <span className="text-amber">Smart</span>
                    </span>
                    {tagline && (
                        <span className="uppercase tracking-[0.28em] text-zinc-500" style={{ fontSize: Math.max(9, size * 0.085) }}>
                            Find what&apos;s worth your time
                        </span>
                    )}
                </div>
            </div>
        );
    }
    return (
        <div className={`flex items-center gap-2.5 ${className}`}>
            {showMark && <Mark size={size} />}
            <span className={`font-display tracking-tight leading-none ${textClassName}`} style={{ fontSize: size * 0.62 }}>
                <span className="text-white">Watch</span>
                <span className="text-amber">Smart</span>
            </span>
        </div>
    );
}
