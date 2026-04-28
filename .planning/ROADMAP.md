# Roadmap: Newz

## Milestones

- ✅ **v1.0 Hackathon MVP** — Phases 1-4 (shipped 2026-04-26, won HackTech 2026)
- 🟡 **v1.1 Pilot MVP for funding** — feature-by-feature, in progress

## v1.1 Pilot MVP — Active

Per-feature GSD: each backlog item becomes its own phase under `.planning/phases/<NN>-<slug>/` when work begins. No fixed sequence — pick by priority + dependency. Mando = blocking for funder demos. Non-mando = nice-to-have if time.

### Mando

| # | Feature | Type | Owner | Status | Phase Dir |
|---|---------|------|-------|--------|-----------|
| 1 | Upload timeout / reliability | Bug | Liam | ✅ Shipped (PR #1, `bccd5d5`) | — |
| 2 | Clip selection logic fix | Bug | Liam | 🟡 Open — montage doesn't seem to pick clips; may need redesign | — |
| 3 | Location bug ("UW shows Pasadena") | Bug | Liam | ✅ Shipped (PR #2, `beda750`) | — |
| 4 | Safari location services bug + permissions gate decision | Bug + Decision | Roan | 🟡 Open — see strategic Q in PROJECT.md | — |
| 5 | **Anonymous comments + shares** | Feature | Roan | 🟢 Planning | `phases/01-comments-and-sharing/` |
| 6 | Video censoring | Feature | TBD | 🟡 Open — approach decision pending | — |
| 7 | Permissions gate (mic + cam + location flow) | Feature | Roan | 🟡 Open — depends on #4 | — |
| 8 | Adding videorecordings to existing montages | Bug | Liam | 🟡 Open — feature exists but doesn't work | — |
| 9 | Real test suite | Infra | Either | 🟡 Open | — |

### Non-mando

| # | Feature | Type | Owner | Status | Phase Dir |
|---|---------|------|-------|--------|-----------|
| 1 | Reduce Claude token usage | Optimization | TBD | 🟡 Open | — |
| 2 | Domain / new name | Branding | TBD | 🟡 Open | — |
| 3 | Custom engagement signal (replaces likes) | Feature | TBD | 🟡 Open — design decision pending | — |
| 4 | Audio embedding | Feature | Liam | 🟡 Open — verify Marengo coverage first | — |
| 5 | Multiple feed tabs (Recent / Popular / Today) | Feature | Roan | 🟡 Open | — |
| 6 | AI comment replies | Feature | TBD | 🟡 Open — depends on Mando #5 shipping | — |

### Considered, then dropped

- **Conventional likes** — content isn't human-authored; human-style "like" carries low signal. Replacement is non-mando #3 (custom signal).
- **"NO DIH PIX" filter as standalone** — folded into video censoring (mando #6).

## Phases

### v1.1 Pilot MVP (active)

- [ ] Phase 01: Anonymous comments + shares — planning · Roan

### v1.0 Hackathon MVP (shipped)

<details>
<summary>✅ v1.0 Hackathon MVP (Phases 1-4) — SHIPPED 2026-04-26</summary>

- [x] Phase 1: Foundation, Capture & Ingest (5/5 plans) — completed 2026-04-25
- [x] Phase 2: Marengo Embedding (2/2 plans) — completed 2026-04-25
- [x] Phase 3: Clustering + Debug Overlay (2/2 plans) — completed 2026-04-25
- [x] Phase 4: Multi-Agent Compile + Real-Time Feed (3/3 plans + parent-cluster pivot) — completed 2026-04-26

Full archive: [milestones/v1.0-ROADMAP.md](./milestones/v1.0-ROADMAP.md)

</details>

---

*v1.1 sequencing is opportunistic — Roan and Liam pull from the table above based on current priority and dependency. Promote a backlog item to a phase by creating `.planning/phases/<NN>-<slug>/` with `<NN>-CONTEXT.md` and `<NN>-PLAN.md`.*
