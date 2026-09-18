---
name: Recommendation impression attribution
description: Rules for joining served feed cards to later user actions in analytics
---

# Recommendation impression attribution

Count each served card once and attribute only its first subsequent terminal
action (`save`, `skip`, or `watched`) when user, impression, and title identity
all match. Report unresponded impressions in the denominator.

**Why:** A user can act on the same title more than once, reverse an action, or
send a stale/mismatched impression identifier. Counting every audit row inflates
conversion and can mix unrelated users or feeds.

**How to apply:** Use this rule for analysis and diagnostics only. Keep the read
bounded, show sample sizes, and do not turn observed conversion into hard
recommendation pool filters.