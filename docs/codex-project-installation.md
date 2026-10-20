# Codex project installation

The tracked `.agents/skills/adaptive-travel-planner` symlink points to the
repository root (`../..`). This exposes the existing `SKILL.md`, `references/`,
`templates/`, and `scripts/` as one project skill without duplicating them.
Keep symlinks enabled when checking out this repository. Start a new Codex task
in this checkout or a child directory, then invoke `$adaptive-travel-planner`.
Do not create a separate worktree merely to use the skill; cloud tasks already
have isolated checkouts. Existing sessions may need to restart discovery.

Codex's documented project discovery directory is `.agents/skills/`:
https://developers.openai.com/codex/skills/

## Development checks

No Node.js installer or running service is required for this local installation.
Python 3.12 was validated in onboarding; CI currently selects Python 3.11.
Create a virtual environment outside the checkout and install the pinned release
dependency:

```bash
python3 -m venv /workspace/.venvs/adaptive-travel-planner
/workspace/.venvs/adaptive-travel-planner/bin/python -m pip install -r requirements-release.txt
```

From the repository root:

```bash
# Only this test process needs the conventional umask: two fixtures assume 0755.
(umask 022; AMAP_API_KEY='' /workspace/.venvs/adaptive-travel-planner/bin/python -m unittest discover -s tests)
/workspace/.venvs/adaptive-travel-planner/bin/python scripts/release_checks.py
/workspace/.venvs/adaptive-travel-planner/bin/python .agents/skills/adaptive-travel-planner/scripts/validate_itinerary.py tests/fixtures/itinerary_valid.json
```

The final command exercises the installed script path with fictional fixture
data; expect `ok: true`, `issue_count: 0`. It is not by itself proof of Codex
discovery. In a new task, invoke the skill explicitly and ask Codex to read its
planning contract and run that command to verify discovery and execution.

## Capability and privacy boundaries

Skill installation does not install a search provider. Before live planning,
verify a real host search/browser query. If none works, use limited mode and
retain unsupported dynamic facts as `unknown` or `login_required`.
AMap is optional, requires separately authorized configuration, and does not
replace general web search. Never enter keys in chat or commit credentials.
Keep real profiles in the existing ignored `references/traveler-profile.md`
or outside the checkout; only fictional fixtures belong in Git.
