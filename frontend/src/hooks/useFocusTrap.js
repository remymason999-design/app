import { useEffect, useRef } from "react";

const FOCUSABLE = [
    "a[href]",
    "button:not([disabled])",
    "input:not([disabled]):not([type='hidden'])",
    "select:not([disabled])",
    "textarea:not([disabled])",
    "[tabindex]:not([tabindex='-1'])",
].join(",");

export default function useFocusTrap(active, onEscape) {
    const ref = useRef(null);
    useEffect(() => {
        if (!active) return;
        const node = ref.current;
        if (!node) return;
        const previouslyFocused = document.activeElement;

        const focusables = () => Array.from(node.querySelectorAll(FOCUSABLE)).filter(
            (el) => !el.hasAttribute("aria-hidden") && el.offsetParent !== null
        );

        const first = focusables()[0];
        if (first) first.focus();

        const onKey = (e) => {
            if (e.key === "Escape" && onEscape) {
                e.stopPropagation();
                onEscape();
                return;
            }
            if (e.key !== "Tab") return;
            const els = focusables();
            if (els.length === 0) return;
            const idx = els.indexOf(document.activeElement);
            if (e.shiftKey && (idx <= 0)) {
                e.preventDefault();
                els[els.length - 1].focus();
            } else if (!e.shiftKey && idx === els.length - 1) {
                e.preventDefault();
                els[0].focus();
            }
        };

        document.addEventListener("keydown", onKey);
        return () => {
            document.removeEventListener("keydown", onKey);
            if (previouslyFocused && previouslyFocused.focus) {
                try { previouslyFocused.focus(); } catch {}
            }
        };
    }, [active, onEscape]);
    return ref;
}
