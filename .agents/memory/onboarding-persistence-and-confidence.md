---
name: Onboarding persistence & per-preference confidence in scoring
description: Why onboarding-genre influence must decay on contradiction (not swipe count) and how per-preference confidence scales ranking influence.
---

# Selected genres decay on contradiction; explicit title evidence has a separate lifecycle

Explicit title answers should seed strong initial taste, but their source-separated
contribution gradually reduces as genuine post-onboarding behaviour accumulates.
Do not apply this fade to selected genres or legacy mixed affinity maps.
Skip in the training deck remains neutral.

**Why:** The expanded onboarding requirements explicitly distinguish strong
initial title training from long-term declared genres, and require newer
behaviour to increasingly dominate without resetting existing users.

**How to apply:** Keep title-training evidence source-separated and decay only
that contribution. Count deliberate distinct post-onboarding title actions,
not impressions, reloads, duplicate requests, or undo/re-save loops.

Onboarding genre selections are a LONG-TERM taste signal. Their scoring influence
must stay strong many sessions later and erode ONLY when the user's later
behaviour contradicts the specific onboarding genre — never as a function of raw
interaction/swipe count.

**Why:** a count-based fade (e.g. multiplier dropping toward a floor after N
swipes) makes a user's declared cold-start preferences vanish purely because time
passed, even if they never rejected that genre. A code review rejected the
count-based model as a direct conflict with the personalisation goal ("a user who
liked Crime/Thriller/Mystery at onboarding should still see them weeks later
unless later behaviour contradicts them").

**How to apply:** gate the onboarding bonus on the user's *learned net genre
weight* for the matched onboarding genre(s): weight ≥ 0 (or unseen) ⇒ uncontradicted
⇒ full strength; weight < 0 ⇒ fade toward a low floor in proportion to the
contradiction. Use the MAX matched weight so a title carrying one still-liked
onboarding genre keeps the bonus. This is a scoring lever only — never a pool
filter, so candidate pools stay byte-identical.

# Per-preference confidence scales influence by evidence

Each learned preference (genre, decade, …) should influence ranking in proportion
to how much evidence backs it: high ≈ 50+ net likes drives ranking, medium ≈ 10,
low ≈ 2 only nudges, below that barely registers. Implemented as an explicit
multiplier on the (already tanh-normalised) learned term. Negative weights
(aversions) keep the full multiplier so dislikes still register fast.

**Why:** tanh magnitude alone was judged insufficient by review — confidence must
be an explicit, evidence-banded multiplier so a thinly-evidenced genre cannot
punch above a well-established one.

**Validation gotcha:** these are ranking changes; they do NOT alter candidate-pool
sizes (pools are built at the filter stage before scoring). The persona sim's
byte-identical requirement is on pool sizes (pFiltr/pBroad), which are unaffected.
Catalog growth from live ingestion DOES change those columns vs an older baseline —
that is ingestion drift, not a scoring regression.
