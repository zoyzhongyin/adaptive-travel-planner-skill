# Codex project installation

The tracked `.agents/skills/adaptive-travel-planner/SKILL.md` is the project
entry, mirroring the root instructions with resource paths adjusted to reach
the canonical repository resources. Keep both instruction bodies synchronized.
Start a new Codex task
in this checkout or a child directory, then invoke `$adaptive-travel-planner`.
Do not create a separate worktree merely to use the skill; cloud tasks already
have isolated checkouts. Existing sessions may need to restart discovery.

Codex's documented project discovery directory is `.agents/skills/`:
https://developers.openai.com/codex/skills/

## Cloud environment with `/workspace` as the task directory

If the cloud task starts in `/workspace` and checks out this repository beneath
it, merge this installer into the branch used by the environment, add this
command to the cloud environment **Install script**, and publish the updated
environment:

```bash
bash /workspace/adaptive-travel-planner-skill/scripts/install_cloud_skill.sh
```

The script must run before the agent starts. It links the repository root at
`/workspace/.agents/skills/adaptive-travel-planner`, so the root `SKILL.md` and
its relative `references/`, `scripts/`, and `templates/` paths stay together.
It is safe to rerun and refuses to replace a different existing installation.
Start a new cloud task after publishing to check automatic Skill registration;
running the command during an existing task cannot redo startup discovery.

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
/workspace/.venvs/adaptive-travel-planner/bin/python scripts/validate_itinerary.py tests/fixtures/itinerary_valid.json
```

The final command exercises the canonical skill script with fictional fixture
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
