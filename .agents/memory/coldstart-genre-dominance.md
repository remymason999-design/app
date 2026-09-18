---
name: Cold-start genre dominance
description: How to make a new user's SELECTED genres dominate their first feeds without lock-in, and the co-tag / popular-pick traps that defeat naive attempts.
---

# Cold-start: make selected genres dominate the first feeds

**Problem:** new users churn when their feed ignores their stated genres (e.g. a
user picks Action/Comedy/Thriller/Crime but sees mostly Drama).

**Approach:** soft, cold-start-only levers (scoring / exploration-ratio /
sampling — never pool filters) that all decay or gate off by the maturity
threshold, so matured scoring is unchanged and there is NO genre lock-in. Always
validate with the persona suite — because it measures at maturity, a green run
confirms the cold-start levers did not leak into matured behaviour.

**Traps to avoid (each cost an iteration):**

- **Do NOT weight the onboarding boost by co-tag COUNT** ("title matches N of my
  genres"). The catalogue's biggest genre (Drama) and Animation are universal
  co-tags on Crime/Action/Thriller titles, so count-weighting surfaces MORE
  off-vibe content, not less. Weight by the selected genre being the title's
  PRIMARY tag instead.
  **Why:** salience, not overlap, is what the user feels.

- **The genre cap is not a genre floor.** A max-per-genre diversify cap does not
  guarantee any genre a MINIMUM share, and a title carrying a second genre slips
  past the cap — so a popular pick (Action, hundreds of hi-popularity titles)
  still floods the core and starves a niche pick (Horror, which exists in supply
  but scores lower). Fix: explicitly round-robin core slots across each selected
  genre, serving the thinnest-supply pick first.
  **Why:** "selected genres dominate" means ALL the user's picks get
  representation, not just the most popular one.

**Data note:** catalogue genre arrays are only ~half salience-ordered (rest
alphabetical), but `genres[0]` still carries enough primary-genre signal to weight
on. Genre label is "Sci-Fi", not "Science Fiction".
