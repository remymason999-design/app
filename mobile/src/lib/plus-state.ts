export interface PlusInterestSnapshot {
  enabled: boolean;
  interested: boolean;
  source_screen?: string | null;
  first_interested_at?: string | null;
  latest_interested_at?: string | null;
  latest_removed_at?: string | null;
}

export type PlusInterestView = "loading" | "error" | "interested" | "disabled" | "available";

export function plusInterestView(input: {
  loading: boolean;
  error: boolean;
  interest?: PlusInterestSnapshot;
  enabled: boolean;
}): PlusInterestView {
  if (input.error) return "error";
  if (input.loading) return "loading";
  if (input.interest?.interested) return "interested";
  if (!input.enabled) return "disabled";
  return "available";
}

export function reconcilePlusInterest(
  current: PlusInterestSnapshot | undefined,
  interested: boolean
): PlusInterestSnapshot {
  return {
    ...(current || { enabled: true }),
    interested,
  };
}