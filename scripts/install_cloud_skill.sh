#!/usr/bin/env bash
set -euo pipefail

repo_root="$(realpath "$(dirname "${BASH_SOURCE[0]}")/..")"
skill_link=/workspace/.agents/skills/adaptive-travel-planner

test -f "$repo_root/SKILL.md"
test -f "$repo_root/references/planning-contract.md"
mkdir -p "$(dirname "$skill_link")"

if [[ -L "$skill_link" ]]; then
    if [[ "$(readlink "$skill_link")" != "$repo_root" ]]; then
        echo "Skill link already points elsewhere: $skill_link" >&2
        exit 1
    fi
elif [[ -e "$skill_link" ]]; then
    echo "Skill path already exists and is not a link: $skill_link" >&2
    exit 1
else
    ln -s "$repo_root" "$skill_link"
fi

test -f "$skill_link/SKILL.md"
test -f "$skill_link/references/planning-contract.md"
printf 'Installed %s -> %s\n' "$skill_link" "$repo_root"
