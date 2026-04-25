# Newz

## What This Is

Newz is AI-native local news from the people who are already recording it. Users point, tap, and submit short clips — anonymously, with GPS auto-attached — and a multi-agent AI pipeline (Claude Agent SDK + Twelve Labs Marengo 3.0) clusters footage of the same event from multiple angles into a structured news segment, served back as a hyperlocal feed. Every user is both journalist and audience — there is no creator/consumer split.

## Core Value

**Multi-angle event clustering must work.** Show the same event captured by different people, automatically grouped and compiled into one coherent segment. If clustering fails, the entire product premise fails.

## Requirements

### Validated

(None yet — ship the hackathon demo to validate)

### Active

- [ ] Anonymous in-app camera: record short clip, tap submit (no account, no caption, no editing)
- [ ] Auto-attach GPS coordinates and timestamp to every submitted clip
- [ ] Backend ingest endpoint that stores clips and triggers embedding
- [ ] Twelve Labs Marengo 3.0 embeddings generated for each clip
- [ ] Event clustering using weighted score (Marengo similarity + GPS proximity + timestamp proximity)
- [ ] Multi-agent compile pipeline (Claude Agent SDK) that produces a news segment per cluster: angle selection, ordering, caption with date/location
- [ ] Local feed UI: scrollable feed of multi-angle video segments ordered by proximity to viewer's GPS + recency
- [ ] One-tap pivot from feed → camera (recorder ↔ viewer is the same loop)
- [ ] Pre-recorded demo dataset (3–4 clips of the same staged event from different angles) to prove clustering accuracy live
- [ ] Visible-to-judges debug view showing Marengo similarity scores, GPS distance, timestamp delta for each cluster

### Out of Scope

- **Live streaming** — clips only; out of scope for hackathon timeline
- **Monetization / creator payments** — not needed for demo, distracts from core flow
- **National/state-level content escalation** — local feed only; hyperlocal IS the differentiator
- **Content moderation pipeline** — acknowledged need, deliberately deferred (mention in pitch, don't build)
- **Native iOS app** — web app sufficient for demo; native is post-hackathon
- **Per-segment engagement features** (likes, clip prioritization, comments) — post-hackathon
- **Captions / titles authored by user** — anonymity + zero friction is the whole point; AI writes everything
- **User profiles / accounts / login** — anonymity by default is a load-bearing differentiator

## Context

**Hackathon:** HackTech (Caltech), April 24–26, 2026. Submitting to four tracks: Best Use of AI, Creativity, YC x HackTech, Sideshift x HackTech.

**Why this project, why now:** Crowd footage already exists (everyone records on their phone) but is scattered across Snapchat, TikTok, group chats, and camera rolls. Traditional news can't cover hyperlocal events economically; social media captures moments but doesn't organize them. The combination of (a) zero-friction anonymous capture, (b) Twelve Labs multimodal video embeddings making automated clustering finally viable, and (c) Claude Agent SDK enabling cheap multi-agent editorial compilation makes this buildable in 2026 in a way it wasn't a year ago.

**The "Best Use of AI" narrative:** Marengo 3.0 produces multimodal video embeddings (visual, motion, audio, speech in one vector) that make event clustering work. A Claude Agent SDK pipeline of distinct agent roles (Angle Selector, Editor, Caption Writer, Publisher) turns a cluster into a finished segment. Two complementary AI systems doing different jobs, both load-bearing.

**Demo strategy:** The product hinges on clustering accuracy. We pre-record 3–4 clips of one staged event from different angles, then show Marengo similarity + GPS + timestamp scores in real time as clips are clustered and compiled. Judges either believe in the magic or don't — the demo must make them believe.

**Team:** Liam + Roan + Claude (co-founder). Claude in the loop building, researching, and deploying throughout.

## Constraints

- **Timeline:** 24–48 hour hackathon build window — scope discipline is non-negotiable
- **Tech stack — Frontend:** React (web app, no native iOS for demo)
- **Tech stack — Backend:** FastAPI (Python — natural fit for Twelve Labs SDK + Claude Agent SDK)
- **Tech stack — Video AI:** Twelve Labs Marengo 3.0 — clustering depends on its multimodal embeddings; non-negotiable
- **Tech stack — Multi-agent AI:** Claude Agent SDK — chosen for narrative strength on "Best Use of AI" track and on-brand co-founder framing
- **Demo:** Must run live in front of judges; offline / partial-network failure modes are real risk
- **Anonymity:** No accounts, no identity ever attached to clips — load-bearing for the value prop, not just a feature

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| React + FastAPI split | Python backend gets first-class Twelve Labs + Anthropic SDKs; React is fastest path to a credible web UI | — Pending |
| Claude Agent SDK for compile pipeline | Strongest "Best Use of AI" story; multi-agent narrative writes itself; on-brand with Claude as co-founder | — Pending |
| Twelve Labs Marengo 3.0 for video embeddings | Multimodal embeddings (visual + motion + audio + speech) are what makes clustering work — no good substitute in 2026 | — Pending |
| Web app, not native iOS | Hackathon demo only needs to work on a phone browser; native is multi-day overhead we can't afford | — Pending |
| Anonymous by default (no accounts) | Removes the biggest barrier to filming sensitive content; differentiator vs Twitter/TikTok | — Pending |
| Clustering = Marengo + GPS + timestamp weighted | Single-signal clustering (any one alone) breaks on adversarial cases; combination is robust | — Pending |
| Pre-recorded demo dataset over live capture | Live demos fail; staged clips de-risk the most important moment of the pitch | — Pending |
| Local feed only (no national/regional) | Hyperlocal IS the differentiator; broadening dilutes the pitch | — Pending |
| No content moderation in v0 | Acknowledged risk; building it eats the build window. Mention in pitch as Day 2 work. | — Pending |

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition** (via `/gsd-transition`):
1. Requirements invalidated? → Move to Out of Scope with reason
2. Requirements validated? → Move to Validated with phase reference
3. New requirements emerged? → Add to Active
4. Decisions to log? → Add to Key Decisions
5. "What This Is" still accurate? → Update if drifted

**After each milestone** (via `/gsd-complete-milestone`):
1. Full review of all sections
2. Core Value check — still the right priority?
3. Audit Out of Scope — reasons still valid?
4. Update Context with current state

---
*Last updated: 2026-04-24 after initialization*
