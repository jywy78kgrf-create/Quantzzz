# The Design Deck — a layered design setup for Claude Code

Five open-source design skill repos, downloaded and wired together into one
layered "design brain" for Claude Code. This is the setup shown in the
reference image (the stacked "01–05" deck): each layer contributes a different
slice of design ability, and together they push Claude's frontend/UI output
from generic to considered.

All **34 skills** from the five repos are **activated** in this repository — see
[How it's wired](#how-its-wired). They only trigger on design / UI work, so they
stay out of the way of the rest of the project.

## The five layers

| # | Layer | Focus | Repo | License | Skills |
|--:|-------|-------|------|---------|:------:|
| 01 | **Impeccable** | Design quality | [`pbakaus/impeccable`](https://github.com/pbakaus/impeccable) | Apache-2.0 | 1 |
| 02 | **Frontend Design** | Anthropic official | [`anthropics/skills`](https://github.com/anthropics/skills) | Apache-2.0 | 1 |
| 03 | **Taste Skill** | Visual taste | [`Leonxlnx/taste-skill`](https://github.com/Leonxlnx/taste-skill) | MIT | 13 |
| 04 | **UI UX Pro Max** | Design knowledge | [`nextlevelbuilder/ui-ux-pro-max-skill`](https://github.com/nextlevelbuilder/ui-ux-pro-max-skill) | MIT | 7 |
| 05 | **Emil's skills** | Motion & interaction | [`emilkowalski/skills`](https://github.com/emilkowalski/skills) | MIT | 12 |

## How the layers stack

Read top to bottom, they form a pipeline from taste → direction → knowledge → motion:

- **01 · Impeccable** shifts the *baseline* — the model's default aesthetic
  distribution — so "AI slop" (purple gradients, glassmorphism, Inter-everywhere)
  isn't generated in the first place. This is the floor everything else sits on.
- **02 · Frontend Design** (Anthropic's official skill) adds *art direction*:
  pick a distinctive point of view, a token system, and one real aesthetic risk
  before any code.
- **03 · Taste Skill** adds an *anti-slop framework* — read the brief, state a
  one-line "design read," then ship interfaces that don't look templated, with
  style-specific variants (minimalist, brutalist, editorial…).
- **04 · UI UX Pro Max** adds *searchable design knowledge* — 79 styles, 192
  palettes, 74 font pairings, 119 UX guidelines, icons, GSAP presets, chart types
  and per-stack implementation notes to ground concrete choices.
- **05 · Emil's skills** add *motion & interaction* craft — when (and when not)
  to animate, spring/gesture physics, and a strict review bar for the invisible
  details that make software feel right.

## What's activated (34 skills)

### 01 · Impeccable — design quality · Apache-2.0
- **`impeccable`** — opinionated design-director skill (v4.1.2) for design,
  redesign, audit, critique, polish, harden, animate and more. User-invocable
  with sub-commands (`/impeccable shape|audit|polish|animate|…`).

### 02 · Frontend Design — Anthropic official · Apache-2.0
- **`frontend-design`** — distinctive, intentional visual design: aesthetic
  direction, typography, and choices that don't read as templated defaults.

### 03 · Taste Skill — visual taste · MIT
- **`design-taste-frontend`** — anti-slop skill for landing pages, portfolios and
  redesigns; infers the right direction from the brief. *(main skill)*
- **`design-taste-frontend-v1`** — the original v1, preserved for compatibility.
- **`minimalist-ui`** — clean editorial interfaces, warm monochrome, bento grids.
- **`industrial-brutalist-ui`** — Swiss print × terminal aesthetics, rigid grids.
- **`high-end-visual-design`** — agency-grade fonts, spacing, shadows, structure.
- **`redesign-existing-projects`** — audit an existing UI and lift it to premium.
- **`full-output-enforcement`** — bans placeholder/truncated code; complete output.
- **`stitch-design-taste`** — generates `DESIGN.md` design-system files.
- **`brandkit`** — brand-guideline boards / identity decks (image generation).
- **`imagegen-frontend-web`** / **`imagegen-frontend-mobile`** — premium design
  *reference images* for web / mobile.
- **`image-to-code`** — image-first web build workflow.
- **`gpt-taste`** — variant tuned for GPT/Codex models (kept for completeness).

### 04 · UI UX Pro Max — design knowledge · MIT
- **`ui-ux-pro-max`** — the core design-intelligence skill (searchable styles,
  palettes, font pairings, UX guidelines, icons, GSAP presets, charts, stacks).
- **`design`** — comprehensive design skill: identity, tokens, UI styling, logos.
- **`design-system`** — three-layer token architecture and component specs.
- **`ui-styling`** — accessible UIs with shadcn/ui + Tailwind.
- **`brand`** — brand voice, visual identity, messaging frameworks.
- **`banner-design`** — banners for social, ads, heroes and print.
- **`slides`** — strategic HTML presentations with Chart.js and design tokens.

### 05 · Emil's skills — motion & interaction · MIT
- **`emil-design-eng`** — Emil Kowalski's design-engineering philosophy (the hub).
- **`animate`** — build an animation from scratch, deciding in the right order.
- **`animate-expo`** — the same, for React Native / Expo.
- **`review-animations`** — review motion code against a strict craft bar.
- **`improve-animations`** — audit a codebase's motion and produce fix plans.
- **`find-animation-opportunities`** — find where motion is missing (and where to reject it).
- **`animation-vocabulary`** — name a vague motion effect ("the bouncy popover thing").
- **`apple-design`** — Apple's fluid, physical motion translated for the web.
- **`prototype`** — build several genuinely different UI versions behind a picker.
- **`pick-ui-library`** — pick the right library for a frontend task.
- **`ask-sonner`** — guide to the Sonner toast library.
- **`write-swift`** — how to write modern Swift well (kept for completeness).

## How it's wired

```
design/skills/<repo>/…        ← the downloaded library (single source of truth,
                                 with each repo's LICENSE + SOURCE.md provenance)
.claude/skills/<skill-name>/  ← 34 relative symlinks into the library above,
                                 one per skill, named by its canonical `name:`
```

Claude Code scans `.claude/skills/` and loads every skill it finds there. The
symlinks keep exactly one copy of each skill on disk while giving each a
top-level, correctly-named entry point.

Re-create or repair the activation layer at any time:

```bash
./design/activate.sh          # (re)create the symlinks (default)
./design/activate.sh --copy   # copy instead of symlink — use on Windows, or if
                              #   your Claude Code build ignores symlinked skills
./design/activate.sh --clean  # deactivate all skills (remove .claude/skills/)
```

## Using it

You don't invoke these by hand — just ask Claude to build or review UI
("design a landing page for …", "audit this component's spacing", "add motion to
this menu") and the relevant skills trigger from their own descriptions. A few
are directly invocable too, e.g. **Impeccable**: `/impeccable init`, then
`/impeccable shape|audit|polish|animate <target>`.

Because every skill is description-gated to design / UI work, they don't fire on
unrelated (e.g. data/quant) tasks in this repo.

## Provenance & licenses

Each `design/skills/<repo>/` directory keeps the upstream **LICENSE** and a
**`SOURCE.md`** recording the exact upstream URL, the vendored commit SHA, and
the download date. Two repos are Apache-2.0 (Impeccable, Frontend Design) and
three are MIT (Taste Skill, UI UX Pro Max, Emil's skills). Only functional skill
content (SKILL.md files, references, scripts, data) plus licenses were vendored —
per-agent duplicate directories, tests, demos, screenshots and build tooling from
the originals were left out to keep this repo lean.

To get the **full** original repos (CLIs, demos, every provider variant), clone
from the upstream URLs in the table above.

## Credits

- **Impeccable** — Paul Bakaus ([@pbakaus](https://github.com/pbakaus))
- **Frontend Design** — Anthropic ([anthropics/skills](https://github.com/anthropics/skills))
- **Taste Skill** — Leonxlnx ([@Leonxlnx](https://github.com/Leonxlnx))
- **UI UX Pro Max** — Next Level Builder ([@nextlevelbuilder](https://github.com/nextlevelbuilder))
- **Emil's skills** — Emil Kowalski ([@emilkowalski](https://github.com/emilkowalski))

The "layered deck" framing of these five skills was popularized by
**@codenameposhan**. This directory just downloads the repos and wires them up;
all skill design and credit belong to the authors above. Not affiliated with or
endorsed by Anthropic or any of the skill authors.
