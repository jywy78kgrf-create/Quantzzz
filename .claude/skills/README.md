# .claude/skills — the activated Design Deck

Every entry here is a **symlink** into the vendored skill library at
[`../../design/skills/`](../../design/skills), named after the skill's canonical
`name:`. Claude Code discovers and loads them automatically. There are 34 skills
across five layers (Impeccable, Frontend Design, Taste Skill, UI UX Pro Max,
Emil's skills).

- Overview, per-skill index, provenance and licenses: [`design/README.md`](../../design/README.md)
- Rebuild / repair these links, or swap to copies: `./design/activate.sh [--copy|--clean]`

Do not edit skills in place here — edit them in `design/skills/` (the single
source of truth) and the change is reflected through the symlink.
