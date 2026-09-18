import { useEffect, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Bell, Check, X, Trash2 } from "lucide-react";
import { apiGet, apiPost, apiDelete } from "@/lib/api";

export default function NotificationBell() {
    const [open, setOpen] = useState(false);
    const [data, setData] = useState({ items: [], unread: 0 });

    const refresh = async () => {
        try {
            const r = await apiGet("/notifications");
            setData(r);
        } catch {}
    };

    useEffect(() => {
        refresh();
        const id = setInterval(refresh, 60000);
        return () => clearInterval(id);
    }, []);

    const markAll = async () => {
        await apiPost("/notifications/read-all");
        await refresh();
    };

    const clearAll = async () => {
        try {
            await apiDelete("/notifications/clear-all");
            setData({ items: [], unread: 0 });
        } catch {}
    };

    return (
        <>
            <button
                onClick={() => { setOpen(true); refresh(); }}
                data-testid="notif-bell"
                aria-label="notifications"
                className="relative h-10 w-10 rounded-full glass grid place-items-center hover:bg-white/[0.06]"
            >
                <Bell className="w-4 h-4 text-zinc-200" strokeWidth={1.7} />
                {data.unread > 0 && (
                    <span className="absolute top-2 right-2 min-w-[18px] h-[18px] px-1 rounded-full bg-amber text-obsidian text-[10px] font-heading grid place-items-center">
                        {data.unread > 9 ? "9+" : data.unread}
                    </span>
                )}
            </button>
            <AnimatePresence>
                {open && (
                    <motion.div
                        className="fixed inset-0 z-[60] bg-obsidian/80 backdrop-blur-sm flex items-start justify-center px-4 pt-16"
                        initial={{ opacity: 0 }}
                        animate={{ opacity: 1 }}
                        exit={{ opacity: 0 }}
                        onClick={() => setOpen(false)}
                        data-testid="notif-panel"
                    >
                        <motion.div
                            initial={{ y: -10, opacity: 0 }}
                            animate={{ y: 0, opacity: 1 }}
                            exit={{ y: -10, opacity: 0 }}
                            transition={{ duration: 0.18 }}
                            onClick={(e) => e.stopPropagation()}
                            className="w-full max-w-md glass-strong rounded-3xl p-5 max-h-[80vh] overflow-auto"
                        >
                            <div className="flex items-center justify-between mb-4">
                                <div className="font-heading text-lg">Notifications</div>
                                <div className="flex items-center gap-2">
                                    {data.unread > 0 && (
                                        <button
                                            onClick={markAll}
                                            className="text-xs text-amber hover:text-amber/80 flex items-center gap-1 px-2 py-1 rounded-lg hover:bg-amber/10 transition-colors"
                                            data-testid="notif-read-all"
                                        >
                                            <Check className="w-3 h-3" /> Mark all read
                                        </button>
                                    )}
                                    {data.items.length > 0 && (
                                        <button
                                            onClick={clearAll}
                                            className="text-xs text-zinc-500 hover:text-red-400 flex items-center gap-1 px-2 py-1 rounded-lg hover:bg-red-500/10 transition-colors"
                                            data-testid="notif-clear-all"
                                            aria-label="clear all notifications"
                                        >
                                            <Trash2 className="w-3 h-3" /> Clear all
                                        </button>
                                    )}
                                    <button
                                        onClick={() => setOpen(false)}
                                        className="h-8 w-8 grid place-items-center rounded-full hover:bg-white/5 transition-colors"
                                        aria-label="close"
                                    >
                                        <X className="w-4 h-4" />
                                    </button>
                                </div>
                            </div>
                            {data.items.length === 0 ? (
                                <div className="py-8 text-center">
                                    <div className="w-12 h-12 rounded-2xl bg-white/5 grid place-items-center mx-auto mb-3">
                                        <Bell className="w-5 h-5 text-zinc-600" strokeWidth={1.5} />
                                    </div>
                                    <p className="text-sm text-zinc-500">All clear — no notifications.</p>
                                </div>
                            ) : (
                                <ul className="space-y-2">
                                    {data.items.map((n, i) => (
                                        <motion.li
                                            key={n.notification_id || i}
                                            layout
                                            initial={{ opacity: 0, y: 4 }}
                                            animate={{ opacity: 1, y: 0 }}
                                            transition={{ delay: i * 0.03 }}
                                            className={`rounded-2xl p-4 border transition-colors ${
                                                n.read ? "border-white/8 bg-white/[0.02]" : "border-amber/25 bg-amber/6"
                                            }`}
                                            data-testid={`notif-${i}`}
                                        >
                                            <div className="font-heading text-sm">{n.title}</div>
                                            <p className="text-xs text-zinc-400 mt-1 leading-relaxed">{n.body}</p>
                                        </motion.li>
                                    ))}
                                </ul>
                            )}
                        </motion.div>
                    </motion.div>
                )}
            </AnimatePresence>
        </>
    );
}
