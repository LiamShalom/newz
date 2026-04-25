# Feature Research

**Domain:** AI-native hyperlocal news / crowdsourced video capture platform
**Researched:** 2026-04-24
**Confidence:** HIGH (Citizen, Watch Duty, Nextdoor, BeReal, TikTok, CNN Shorts, Snap Map are all extensively documented; demo wow factors verified against hackathon judging criteria)

---

## Feature Landscape

### Table Stakes (Users Bounce / Judges Lose Confidence Without These)

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| **One-tap-to-record from feed** | Citizen, BeReal, TikTok, Snap all open camera-first or one-tap from feed. Two+ taps to start recording feels broken in 2026. | LOW | Single floating action button on feed; tap → preview → record. Recorder ↔ viewer is the same loop (already in PROJECT.md). |
| **Pre-permission priming for camera + GPS** | NN/g research: contextual permission asks see 28% higher grant rate; explanation screens lift grants up to 81%. Cold browser permission prompts on app open will tank submission rate. | LOW | Show "We need camera + location to attach this clip to where it happened" modal BEFORE the browser dialog. Ask both at the moment of first record tap, not on app open. |
| **Visible recording indicator + duration counter** | Standard since iOS camera. Users panic-tap stop without it. | LOW | Red dot, MM:SS counter, hard cap at 30s for clip length (forces brevity, keeps Marengo embedding cost down). |
| **Auto-attach GPS + timestamp (silent, visible)** | Already in PROJECT.md. Watch Duty + Citizen both show location confidence as a trust signal — invisible attachment is suspicious. | LOW | "Attaching: 2 blocks from you, just now" microcopy under preview. |
| **Submit-or-discard preview screen** | Skipping preview = users submit shaky/wrong clips and stop trusting the app. BeReal, Snap, TikTok all preview before post. | LOW | Single screen, two buttons: "Post" / "Retake". No editing — anonymity + zero friction means no captions/filters/trims. |
| **Vertical scrolling feed (TikTok-shaped)** | CNN Shorts (Nov 2025), X, Netflix, NYT have all moved to vertical TikTok-style feeds for news in 2025-2026. Anything else feels dated. | MEDIUM | Full-screen autoplay, swipe up = next segment. Tap to mute/unmute. Scroll position resumes on return. |
| **Proximity + recency feed sort** | Hyperlocal IS the differentiator (PROJECT.md). Nextdoor users actively complain when feed isn't tight to their neighborhood. | MEDIUM | Default sort = weighted (distance × recency). Already in active requirements. |
| **Visible distance + age on each segment** | "2 blocks away · 4 min ago" is the hyperlocal hook. Without it, the feed is just another video feed. | LOW | Overlay at top-left of segment. Use relative time ("just now", "12m ago") per news feed UX standards. |
| **Loading state during compile (not blank screen)** | Multi-agent compile is slow (10-30s). Blank loading kills demo momentum. | LOW | "AI is compiling 4 angles..." with progress phases ("clustering → selecting angles → writing caption"). Doubles as wow factor (see below). |
| **Graceful empty state for "no events near you"** | Demo will run in a venue with no submissions yet. Empty feed = product looks broken. | LOW | "No events captured nearby — be the first" + big record CTA. Pre-seed demo dataset clusters as backup. |
| **Network failure recovery on submit** | Hackathon venue WiFi is hostile. A failed upload that loses the clip = catastrophic demo moment. | MEDIUM | Local persist of clip blob until server ACK. Retry with exponential backoff. Show "Saved, retrying..." not "Failed". |
| **Source clip count visible on segment** | "Compiled from 4 angles" is the trust signal that replaces account-based credibility. Watch Duty's whole verification model is "multiple confirmations". | LOW | Badge: "4 angles · 3 contributors". Already implied by debug view, but needs a non-debug version on segment cards. |

### Differentiators (Newz vs. Citizen / TikTok / Watch Duty)

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| **Multi-angle compiled segment (the core)** | Citizen shows one livestream per incident. TikTok shows N independent clips. Newz fuses N clips of the same event into one structured segment with cuts, ordering, and AI caption. **This is the entire product premise.** | HIGH | Already in active requirements. Claude Agent SDK pipeline: Angle Selector → Editor → Caption Writer → Publisher. Non-negotiable for demo. |
| **Marengo-driven similarity clustering (visible)** | Citizen relies on human moderators; Watch Duty on volunteer fire spotters. Newz uses Marengo 3.0 multimodal embeddings (visual + motion + audio + speech) — automated, scales infinitely. | HIGH | Core technical novelty. Show the similarity score in the demo debug view to make this concrete to judges. |
| **Anonymous-by-default (no accounts ever)** | BeReal forces face-on-post. Citizen requires sign-up. TikTok requires account. Newz is the only platform where you can submit footage of sensitive events with zero identity attached. Load-bearing for the value prop, not just a feature. | LOW | Already locked. Differentiator framing: "We don't have a sign-in screen, by design." |
| **AI-written segment captions with date + location** | Citizen captions are user-written or moderator-edited. Newz auto-writes AP-wire-style captions ("Police activity at 3rd & Main, Pasadena · 4:32 PM PDT, April 25") that sound editorial without a human. | MEDIUM | Last agent in the Claude Agent SDK pipeline. Templated structure + LLM fill-in keeps it reliable for demo. |
| **Recorder ↔ viewer same loop (no creator/audience split)** | TikTok creator economy explicitly splits creator/consumer. Newz pivot from feed to camera in one tap reframes everyone as a journalist. Strong narrative for the YC track. | LOW | Already in active requirements as "one-tap pivot". |
| **Cluster confirmation count as trust signal** | Twitter Community Notes uses crowd ratings; Watch Duty uses verified spotters. Newz uses *cluster size* — 4 independent clips of the same event from different angles = high confidence. No identity required. | MEDIUM | Display "Confirmed by N independent angles" prominently. Tie to cluster size threshold (e.g., 2+ angles = "confirmed"). |
| **Hyperlocal-only feed (no national escalation)** | Citizen recently expanded to 15 cities and is becoming national. Watch Duty went nationwide in 2026. Both are losing the *neighborhood* feel. Newz stays small on purpose. | LOW | Already locked in scope. Pitch framing: "We will never have a national feed." |

### Demo Wow Factor (Win the Judges)

These are concrete, named features specifically engineered to make judges lean forward. Focus on three: live clustering visualization, similarity score overlay, and the visible multi-agent pipeline.

| Feature | Why Judges React | Complexity | Notes |
|---------|------------------|------------|-------|
| **Live clustering visualization (the money shot)** | Show 3-4 demo clips arriving, then a real-time animation where they "snap" into one cluster as Marengo similarity crosses threshold. Judges *see* the AI working. | MEDIUM | Animate cluster formation in the debug/judge view. Use the pre-recorded demo dataset (PROJECT.md) — submit clips one-by-one on stage, watch them fuse. |
| **Visible similarity scores (HIGH confidence — verified against PROJECT.md debug requirement)** | Marengo similarity 0.87, GPS distance 12m, timestamp delta 38s. Numbers on screen = "this is real, not vibes." Already committed in PROJECT.md active requirements. | LOW | Toggle-able debug overlay. Default off in user view, default on in demo view. |
| **Multi-agent pipeline visualization** | Show the four Claude agents (Angle Selector → Editor → Caption Writer → Publisher) lighting up in sequence as they work. Each emits a 1-line status. Makes the "Best Use of AI" track narrative concrete. | MEDIUM | Stream agent status to frontend during compile. "Angle Selector: chose 3 of 4 clips · Editor: ordered by action density · Caption Writer: drafted headline · Publisher: shipped." |
| **Auto-generated AP-wire-style caption appearing live** | The caption *types itself* during compile (streaming LLM output). Cinematic moment. | LOW | Stream Claude tokens to UI. Cheap, looks expensive. |
| **Side-by-side angle preview before compile** | Show the 3-4 raw clips in a grid, then they merge into one compiled segment. Visualizes the value prop (multi-angle → one segment) better than any pitch slide. | MEDIUM | Grid view in demo mode only. Skip in user app to keep UX clean. |
| **One-tap pivot: feed → camera → submit → cluster on screen** | The full demo loop runs in <60 seconds: scroll feed, tap record, capture clip, watch it cluster into existing event, refresh feed, see compiled segment. End-to-end magic. | MEDIUM | This is the killer demo arc. All pieces already in active requirements; just rehearse the choreography. |
| **"Anonymous" badge prominently on every segment** | Counterintuitive feature in a demo culture obsessed with creators. Judges remember it. | LOW | Subtle but consistent design element. Reinforces the differentiator visually. |

**Demo wow factor priority for the 3-minute pitch:**
1. Live clustering visualization (must-have — this is THE moment)
2. Visible similarity scores (must-have — already committed)
3. Multi-agent pipeline visualization (must-have for "Best Use of AI" track)
4. Streaming AP-wire caption (high-leverage, low-cost)
5. Side-by-side angle preview (cut if time-constrained)

### Anti-Features (Deliberately NOT Building)

| Feature | Why Requested | Why Problematic | Alternative |
|---------|---------------|-----------------|-------------|
| **Live streaming** | Citizen does it; feels modern. | Massive infra (WebRTC, transcoding, edge servers). Blows the 24-48hr build window. PROJECT.md already excludes. | Short clips only. Pitch framing: "We're betting on edited segments over raw streams." |
| **Likes / comments / reactions** | Every social app has them. Judges may ask about engagement loop. | Adds moderation surface area, requires identity model, distracts from clustering. | Cluster size = implicit engagement signal ("4 people captured this"). Anonymity is the differentiator. |
| **User-authored captions / titles** | Standard on TikTok / Instagram. | Defeats anonymity (writing style is identity). Adds friction to capture. AI caption is the editorial moat. | All captions AI-generated. PROJECT.md already excludes. |
| **Accounts / profiles / login** | Standard on every platform. Investors will ask about retention/CAC. | Defeats the entire value prop (anonymous capture of sensitive footage). | Anonymous-by-default. Address retention question in pitch: "Push notifications on local breaking events drive return — no account needed." |
| **Content moderation pipeline** | Obvious risk for a UGC platform. Judges may flag it. | Multi-week build. Eats the hackathon window. PROJECT.md already excludes. | Acknowledge in pitch as Day 2 work. Mention cluster-confirmation as a passive moderation signal (multiple-source agreement filters out solo bad actors). |
| **National / state-level feed** | Apparent "scaling" feature. | Citizen and Watch Duty have both expanded nationally and lost their neighborhood feel. Becoming "another news app" defeats hyperlocal differentiation. | Hyperlocal forever. Different cities = different installs / different feeds. |
| **Native iOS app** | Better camera access, smoother video. | Multi-day build. Web app is sufficient on a phone browser for demo. | React PWA with `getUserMedia` + camera capture. PROJECT.md already locked. |
| **In-app editing (trim, filters, music)** | Standard on TikTok / Snap. | Adds friction to capture. Defeats the "tap and submit" promise. AI does all editing in the compile pipeline. | Submit raw, AI edits. The pipeline IS the editor. |
| **User-driven clip prioritization within a cluster** | Empowers contributors; feels democratic. | Reintroduces identity (who's voting?). Adds moderation surface. Slows compile. | Angle Selector agent picks. Trust the AI; that's the whole pitch. |
| **Per-segment engagement metrics (views, share count)** | Standard analytics. | Implies a creator economy that doesn't exist here. Anonymity makes per-creator metrics meaningless. | Cluster size + age + proximity are the only signals shown. |
| **Scheduled / time-prompted capture (BeReal-style "Time to BeReal")** | Forces engagement; viral mechanic. | Newz is event-driven, not schedule-driven. Local events happen on their own clock — manufacturing capture moments breaks the credibility. | Push notification when a *nearby event* clusters with N+ angles ("Something's happening 2 blocks away"). Event-triggered, not time-triggered. |
| **Map view of incidents (Snap Map / Citizen-style)** | Visual, intuitive, expected for location-based apps. | Significant UI work. Steals demo time from the clustering story. Feed already shows distance. | Defer to v1.x. If asked, "We have GPS-sorted feed; map view is one screen away." |
| **Search / topic filtering** | Standard for news apps. | Hyperlocal feed is small enough that filtering is unnecessary. Adds UI weight. | Scroll the feed. If you can't find it, it didn't happen near you. |

---

## Feature Dependencies

```
Anonymous capture (active)
    └──requires──> Camera + GPS permission flow (active)
                       └──requires──> Pre-permission priming (table stakes)

Marengo embedding (active)
    └──requires──> Backend ingest + storage (active)
                       └──requires──> Network retry on submit (table stakes)

Cluster compile (active)
    ├──requires──> Marengo embeddings (active)
    ├──requires──> GPS proximity scoring (active)
    └──requires──> Timestamp proximity scoring (active)

Multi-agent pipeline (active)
    └──requires──> Cluster compile (active)
                       └──enables──> AP-wire caption (differentiator)
                       └──enables──> Multi-agent visualization (wow)

Local feed (active)
    ├──requires──> Compiled segments exist (active)
    ├──requires──> Viewer GPS (table stakes — same permission as capture)
    └──enhances──> Distance + age overlay (table stakes)

One-tap pivot feed→camera (active)
    └──requires──> Local feed + camera both built (active)
    └──enables──> Demo loop choreography (wow)

Live clustering visualization (wow)
    ├──requires──> Debug view with similarity scores (active)
    └──requires──> Pre-recorded demo dataset (active)

Cluster size as trust signal (differentiator)
    └──requires──> Source clip count exposed in API (table stakes)

Anti-features explicitly conflict with active requirements:
- Accounts ──conflicts──> Anonymous capture (load-bearing)
- User captions ──conflicts──> AI caption pipeline (the editorial moat)
- Live streaming ──conflicts──> Hackathon timeline
- National feed ──conflicts──> Hyperlocal differentiation
```

### Dependency Notes

- **Pre-permission priming MUST come before camera/GPS browser prompts.** Cold browser dialogs on app open will tank submission rate (NN/g: 28% higher grant rate with priming, up to 81% lift with explanation copy).
- **Source clip count exposure is the bridge from active requirements to the trust-signal differentiator.** API already needs to return cluster members for the debug view; surfacing the count in the feed is near-zero additional work.
- **Network retry on submit is a hidden dependency on demo success.** Hackathon WiFi will fail. Without local persist + retry, a failed upload during the live demo loses the clip and breaks the choreography.
- **The demo loop choreography depends on five things working together:** feed → camera pivot, camera → submit, submit → ingest → embed → cluster, cluster → compile, compile → feed refresh. Any single break kills the demo. Rehearse end-to-end.
- **Live clustering visualization depends on the pre-recorded demo dataset.** Live capture during the pitch is too risky (lighting, audio, crowd movement breaking Marengo similarity). Pre-recorded clips submitted on stage = controllable, repeatable.

---

## MVP Definition

### Launch With (Hackathon Demo / v0)

These are non-negotiable for the demo. All map directly to PROJECT.md active requirements OR are necessary supporting UX.

- [ ] **Anonymous in-app camera with one-tap record** — entry point to the entire product
- [ ] **Pre-permission priming modal** — without it, browser permission denials kill the demo
- [ ] **Auto-attach GPS + timestamp (with visible microcopy)** — table stakes + trust signal
- [ ] **Submit-or-retake preview screen** — prevents bad submissions, sets quality floor
- [ ] **Backend ingest endpoint with local-persist retry** — hackathon WiFi resilience
- [ ] **Marengo 3.0 multimodal embedding** — clustering depends on this
- [ ] **Weighted clustering (Marengo + GPS + timestamp)** — core technical promise
- [ ] **Multi-agent compile pipeline (Claude Agent SDK)** — "Best Use of AI" narrative
- [ ] **AP-wire-style auto-caption with date + location** — editorial credibility without a human
- [ ] **Vertical TikTok-style feed sorted by proximity + recency** — table stakes feed UX
- [ ] **Distance + age overlay per segment** — hyperlocal hook
- [ ] **Source clip count badge ("Compiled from N angles")** — trust signal that replaces accounts
- [ ] **One-tap pivot from feed to camera** — recorder ↔ viewer loop
- [ ] **Pre-recorded demo dataset (3-4 clips, staged event)** — de-risk the demo
- [ ] **Visible-to-judges debug view (similarity, GPS distance, timestamp delta)** — judges see the AI working
- [ ] **Live clustering visualization (animation when clips fuse)** — THE wow moment
- [ ] **Multi-agent pipeline status stream** — visualizes the "Best Use of AI" story
- [ ] **Empty state with record CTA** — graceful when feed is empty
- [ ] **Loading state during compile (with phases)** — preserves demo momentum

### Add After Validation (Post-Hackathon / v1.x)

- [ ] **Push notification on nearby event clustering** — drives return without accounts
- [ ] **Map view of recent segments** — natural extension of GPS data; defer to keep demo focused
- [ ] **Native iOS app** — better camera access, smoother record. PWA is fine for demo.
- [ ] **Content moderation pipeline (cluster-aware)** — acknowledged Day 2 work
- [ ] **Per-event timeline (view all source clips)** — power-user view
- [ ] **Adjustable feed radius** — Nextdoor pattern; users want control over locality
- [ ] **Replay / share segment to external platforms** — distribution beyond Newz

### Future Consideration (v2+)

- [ ] **Live streaming for breaking events** — only after clip-based product is validated
- [ ] **Multi-language AI captions** — extends to non-English markets
- [ ] **Verified contributor lanes** — opt-in identity for journalists/officials, while preserving anonymous-by-default
- [ ] **Cross-cluster event timeline** ("This story over 6 hours") — emerges once we have N hours of dense capture
- [ ] **Editor override / human-in-the-loop for high-stakes events** — partnership play with newsrooms
- [ ] **Audio-only capture** — for events where filming is risky

---

## Feature Prioritization Matrix

| Feature | User Value | Implementation Cost | Priority |
|---------|------------|---------------------|----------|
| One-tap record + preview + submit | HIGH | LOW | P1 |
| Pre-permission priming | HIGH | LOW | P1 |
| Auto-attach GPS + timestamp | HIGH | LOW | P1 |
| Marengo embedding + weighted clustering | HIGH | HIGH | P1 |
| Multi-agent compile pipeline | HIGH | HIGH | P1 |
| AP-wire AI caption | HIGH | MEDIUM | P1 |
| Vertical feed sorted by proximity/recency | HIGH | MEDIUM | P1 |
| Distance + age + cluster size overlays | HIGH | LOW | P1 |
| One-tap feed → camera pivot | MEDIUM | LOW | P1 |
| Pre-recorded demo dataset | HIGH (for demo) | LOW | P1 |
| Debug view with similarity scores | HIGH (for judges) | LOW | P1 |
| Live clustering visualization | HIGH (for demo) | MEDIUM | P1 |
| Multi-agent pipeline visualization | HIGH (for judges) | MEDIUM | P1 |
| Network retry / local-persist on submit | HIGH (for demo) | MEDIUM | P1 |
| Empty state + loading state | MEDIUM | LOW | P1 |
| Push notification on nearby cluster | HIGH | MEDIUM | P2 |
| Map view of incidents | MEDIUM | HIGH | P2 |
| Native iOS app | MEDIUM | HIGH | P2 |
| Content moderation | HIGH (long-term) | HIGH | P2 |
| Adjustable feed radius | MEDIUM | LOW | P2 |
| Live streaming | LOW (premature) | HIGH | P3 |
| Verified contributor lanes | MEDIUM | HIGH | P3 |
| Cross-cluster event timeline | MEDIUM | HIGH | P3 |

**Priority key:**
- P1: Required for hackathon demo. If any P1 ships broken, the demo is at risk.
- P2: Post-hackathon, add as users validate the core loop.
- P3: Future consideration; build only after PMF on the hyperlocal anonymous loop.

---

## Competitor Feature Analysis

| Feature | Citizen | Watch Duty | Nextdoor | TikTok | BeReal | Newz |
|---------|---------|------------|----------|--------|--------|------|
| Anonymous capture | No (sign-up required) | No (volunteer/officer roles) | No (real names enforced) | No (account) | No (face-on-post) | **Yes — load-bearing** |
| Multi-angle event fusion | No (one livestream per incident) | No (text reports + photos) | No (single posts) | No (independent clips) | No | **Yes — core differentiator** |
| Trust without identity | No (moderator review) | No (vetted volunteers) | No (real names) | No (followers) | No (friends) | **Cluster confirmation count** |
| AI-compiled segments | No (human moderators caption) | No (human officers write) | No | Algorithmic feed only | No | **Yes — Claude Agent SDK pipeline** |
| Hyperlocal-only | No (15 cities, scaling) | No (nationwide as of 2026) | Yes (neighborhood) | No (global feed) | No (friends) | **Yes — locked, no national plan** |
| Vertical TikTok-style feed | Partial (live tiles) | No (map + list) | No (timeline) | Yes | No (single post/day) | **Yes — table stakes** |
| One-tap record from feed | Partial (Alert Community button) | No (capture isn't core) | No | Yes | Yes (notification → capture) | **Yes** |
| Multimodal AI clustering | No (human triage) | No (human verification) | No | No (engagement signals) | No | **Yes — Marengo 3.0 embeddings** |
| Map view | Yes | Yes (primary view) | Partial | No | No | Deferred to v1.x |
| Live streaming | Yes | No | No | Yes | No | **Explicit anti-feature** |

**Newz's positioning:** Anonymous + multi-angle + AI-compiled + hyperlocal-only is a four-axis combination no listed competitor occupies. Citizen is the closest by domain (incident reporting) but is identity-bound, single-stream, and scaling national. Watch Duty proves crowdsourced verification works but uses humans, not multimodal AI. The differentiation is defensible.

---

## Sources

- [Citizen App — Real-time alerts and incident reporting](https://citizen.com/)
- [Citizen Help: How to report an incident](https://support.citizen.com/hc/en-us/articles/115000424533-Can-I-report-an-incident-on-Citizen)
- [Citizen expansion to 15 new cities (Mar 2026)](https://www.prnewswire.com/news-releases/citizen-brings-real-time-safety-to-15-new-cities-302717025.html)
- [Watch Duty — Real-time wildfire maps and human-vetted alerts](https://www.watchduty.org/)
- [Watch Duty nationwide expansion (2026)](https://www.watchduty.org/blog/watch-duty-expands-nationwide-to-deliver-trusted-real-time-wildfire-alerts-across-the-u-s)
- [How Watch Duty became essential during LA wildfires (CBS News)](https://www.cbsnews.com/news/watch-duty-app-los-angeles-wildfires-warnings-evacuations/)
- [Nextdoor — Neighborhood network and emergency alerts](https://nextdoor.com/)
- [Nextdoor AI-driven features and real-time safety alerts](https://www.bbntimes.com/technology/nextdoor-upgrades-platform-with-ai-driven-features-neighborhood-news-and-real-time-safety-alerts)
- [BeReal UX case study (Medium)](https://oodesignernari.medium.com/redesigned-bereal-an-ux-case-study-6a12521f9045)
- [BeReal UX flow analysis (Page Flows)](https://pageflows.com/ios/products/bereal/)
- [TikTok UI/UX product analysis](https://chougeena.medium.com/why-tiktok-is-addictive-a-product-design-and-ux-analysis-149f429d55c3)
- [TikTok UI choices that made the app successful](https://www.iteratorshq.com/blog/5-tiktok-ui-choices-that-made-the-app-successful/)
- [CNN adds TikTok-style vertical Shorts feed (Nov 2025)](https://www.broadbandtvnews.com/2025/11/11/cnn-adds-tiktok-style-vertical-shorts-feed-to-flagship-app/)
- [Netflix vertical video feed and AI recommendations (TechCrunch, Apr 2026)](https://techcrunch.com/2026/04/17/netflix-plans-to-add-a-vertical-video-feed-use-ai-for-recommendations/)
- [NYT vertical video strategy (briefing.center)](https://briefing.center/news/how-tiktok-inspired-new-york-times-vertical-video-strategy)
- [Twitter Community Notes — Wikipedia](https://en.wikipedia.org/wiki/Community_Notes)
- [Crowdsourced fact-checking effectiveness (ScienceDirect)](https://www.sciencedirect.com/science/article/pii/S0306457324001523)
- [GNSS + blockchain for citizen journalism credibility (Nature Scientific Reports, 2025)](https://www.nature.com/articles/s41598-025-04231-w)
- [Multi-camera video event clustering (PMC)](https://pmc.ncbi.nlm.nih.gov/articles/PMC10422581/)
- [FOCUS: Clustering crowdsourced videos by line-of-sight](https://www.researchgate.net/publication/261562453_FOCUS_Clustering_crowdsourced_videos_by_line-of-sight)
- [Multi-view video discovery and organization (ScienceDirect)](https://www.sciencedirect.com/science/article/abs/pii/S0020025514008159)
- [Mobile permission request best practices (NN/g)](https://www.nngroup.com/articles/permission-requests/)
- [Mobile permission priming strategies (Appcues)](https://www.appcues.com/blog/mobile-permission-priming)
- [Web permissions best practices (web.dev)](https://web.dev/articles/permissions-best-practices)
- [Hackathon demo presentation tips (Devpost)](https://info.devpost.com/blog/how-to-present-a-successful-hackathon-demo)
- [Hackathon demo video best practices (Devpost)](https://info.devpost.com/blog/6-tips-for-making-a-hackathon-demo-video)
- [AI news anchor / auto-generated video segments (HeyGen)](https://www.heygen.com/tool/ai-news-generator)
- [AI Studios — local news AI anchors in production (Fox 26)](https://www.aistudios.com/blog/three-reasons-why-news-stations-are-using-ai-anchor)

---

*Feature research for: AI-native hyperlocal news / crowdsourced video capture (Newz)*
*Researched: 2026-04-24*
