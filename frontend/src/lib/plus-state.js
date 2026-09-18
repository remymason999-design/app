export function plusInterestView({ loading, error, interest, enabled }) {
    if (error) return "error";
    if (loading) return "loading";
    if (interest?.interested) return "interested";
    if (!enabled) return "disabled";
    return "available";
}

export function reconcilePlusInterest(current, interested) {
    return {
        ...(current || { enabled: true }),
        interested: Boolean(interested),
    };
}