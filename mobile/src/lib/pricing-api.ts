/**
 * Subscription pricing API helpers for the native app.
 *
 * GET /pricing/services → the streaming services the user can pick from, each
 * with its nested list of plans. Plans carry the real commercial detail we use
 * to build the plan selector (price, ad-support, video quality, simultaneous
 * streams, billing type, add-on / promo flags).
 *
 * Response/field shapes mirror the FastAPI backend exactly — do not invent
 * fields.
 */
import { api } from "@/lib/api";

export type BillingType = "monthly" | "annual" | "free" | "licence_required";

export interface PricingPlan {
  id: string;
  service_id: string;
  name: string;
  monthly_price: number | null;
  annual_price: number | null;
  billing_type: BillingType;
  has_ads: boolean | null;
  video_quality?: string | null;
  simultaneous_streams?: number | null;
  addon: boolean;
  is_promo: boolean;
  active: boolean;
}

export interface PricingService {
  id: string;
  name: string;
  logo_path?: string | null;
  logo_color?: string | null;
  plans: PricingPlan[];
}

export async function fetchPricingServices(): Promise<PricingService[]> {
  // Backend returns { services: [...] }.
  const r = await api.get<{ services: PricingService[] } | PricingService[]>(
    "/pricing/services",
  );
  return Array.isArray(r.data) ? r.data : r.data.services ?? [];
}

// ---------------------------------------------------------------------------
// Selection persistence shape (sent alongside `subscriptions` to
// PUT /user/preferences).
// ---------------------------------------------------------------------------
export type BillingCycle = "monthly" | "annual";

export interface SubscriptionPlanSelection {
  plan_id: string | null;
  billing_cycle: BillingCycle;
  effective_monthly_cost: number;
  included_with_other_provider: boolean;
  custom_price: number | null;
}

export type SubscriptionPlansMap = Record<string, SubscriptionPlanSelection>;

// ---------------------------------------------------------------------------
// Plan-selector helpers (shared by onboarding + profile)
// ---------------------------------------------------------------------------

/** Plans eligible for the primary chooser: active, non-add-on. */
export function primaryPlans(plans: PricingPlan[]): PricingPlan[] {
  return plans.filter((p) => p.active && !p.addon);
}

/** Active add-on plans (e.g. Boost), shown as optional extras. */
export function addonPlans(plans: PricingPlan[]): PricingPlan[] {
  return plans.filter((p) => p.active && p.addon);
}

export function isFreePlan(p: PricingPlan): boolean {
  return p.billing_type === "free";
}

export function isLicencePlan(p: PricingPlan): boolean {
  return p.billing_type === "licence_required";
}

export function isPaidPlan(p: PricingPlan): boolean {
  return !isFreePlan(p) && !isLicencePlan(p);
}

/**
 * Default highlighted plan for a service: the cheapest paid plan (by monthly
 * price). Free / licence-only services default to their single plan. Returns
 * null if there are no eligible plans. The user must still explicitly confirm.
 */
export function defaultHighlightPlan(plans: PricingPlan[]): PricingPlan | null {
  const eligible = primaryPlans(plans);
  if (eligible.length === 0) return null;
  const paid = eligible.filter(isPaidPlan);
  if (paid.length === 0) return eligible[0];
  return [...paid].sort(
    (a, b) => (a.monthly_price ?? Infinity) - (b.monthly_price ?? Infinity)
  )[0];
}

/**
 * Effective monthly cost for a plan under the given options.
 * - Included with another provider → £0 (unless a custom price is set).
 * - Custom price → treated as a monthly figure.
 * - Free / licence-required → £0.
 * - Annual billing → annual_price / 12 where present, else monthly_price.
 */
export function effectiveMonthlyCost(
  plan: PricingPlan | null,
  opts: {
    billingCycle: BillingCycle;
    includedWithOther: boolean;
    customPrice: number | null;
  }
): number {
  if (opts.customPrice != null && !Number.isNaN(opts.customPrice)) {
    return opts.includedWithOther ? 0 : opts.customPrice;
  }
  if (opts.includedWithOther) return 0;
  if (!plan) return 0;
  if (isFreePlan(plan) || isLicencePlan(plan)) return 0;
  if (opts.billingCycle === "annual" && plan.annual_price != null) {
    return plan.annual_price / 12;
  }
  return plan.monthly_price ?? 0;
}
