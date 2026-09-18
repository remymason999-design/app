import { Link } from "react-router-dom";
import { ArrowLeft } from "lucide-react";

function Page({ title, children }) {
    return (
        <div className="min-h-screen px-6 py-12 max-w-2xl mx-auto">
            <Link to="/" className="inline-flex items-center gap-2 text-xs uppercase tracking-[0.22em] text-zinc-500 mb-8">
                <ArrowLeft className="w-3 h-3" /> Back
            </Link>
            <h1 className="font-display text-4xl mb-6">{title}</h1>
            <div className="prose prose-invert text-sm text-zinc-300 leading-relaxed space-y-4">
                {children}
            </div>
        </div>
    );
}

export function Terms() {
    return (
        <Page title="Terms of Service">
            <p>By using WatchSmart you agree to these terms. WatchSmart is a recommendation
            service — we help you decide what to watch across the streaming services you
            already pay for. We do not stream content ourselves.</p>
            <p><b>Your account.</b> You're responsible for keeping your password safe and for
            activity on your account. We may suspend accounts that abuse the service or
            attempt to scrape our data.</p>
            <p><b>Subscriptions.</b> WatchSmart is free. Streaming subscriptions you connect
            are billed by their respective providers — we never touch your billing.</p>
            <p><b>Liability.</b> WatchSmart is provided "as is" without warranty. We aren't
            liable for content unavailability, provider outages, or inaccurate availability
            data sourced from third parties.</p>
            <p><b>Changes.</b> We may update these terms. Continued use after an update means
            you accept the revised terms.</p>
            <p className="text-zinc-500 text-xs">Contact: support@watchsmart.uk</p>
        </Page>
    );
}

export function Privacy() {
    return (
        <Page title="Privacy Policy">
            <p><b>What we collect.</b> Your email, name, optional DOB/gender, the streaming
            services you select, your saves/skips/watches, search queries, and learned taste
            weights. We use this only to personalise your recommendations.</p>
            <p><b>What we don't.</b> We never sell your data. We don't track you across the
            web. We don't share your watch history with third parties.</p>
            <p><b>Cookies.</b> We use a single authentication cookie to keep you signed in.
            We don't use any advertising cookies.</p>
            <p><b>Analytics &amp; error monitoring.</b> We use privacy-friendly product
            analytics (PostHog) to understand how the app is used, and error monitoring
            (Sentry) to detect and fix crashes. These help us improve WatchSmart — we
            never sell this data or use it for advertising.</p>
            <p><b>Email.</b> We send a welcome email on signup, a password-reset email when
            you request one, and (optionally) feature/changelog updates which you can turn
            off any time.</p>
            <p><b>Data export &amp; deletion.</b> You can download a complete copy of your
            data any time from Profile → "Download my data". You can also permanently
            delete your account from Profile → "Delete my account" — this removes or
            anonymises all your data.</p>
            <p><b>Contact.</b> Questions or data requests? Email us at{" "}
            <a href="mailto:support@watchsmart.uk" className="text-amber hover:underline">support@watchsmart.uk</a>.</p>
            <p className="text-zinc-500 text-xs">Contact: support@watchsmart.uk</p>
        </Page>
    );
}
