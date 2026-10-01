from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

from .catalog import CapabilityHandler
from .models import Capability, CapabilityKind


@dataclass(frozen=True)
class LoadedSkill:
    descriptor: Capability
    instructions: str
    root: Path

    def build_handler(self) -> CapabilityHandler:
        instructions = self.instructions
        root = self.root

        async def execute(payload: dict) -> dict:
            return {
                "skill_instructions": instructions,
                "skill_root": str(root),
                "invocation_reason": payload["instruction"],
                "context_count": len(payload.get("context", [])),
            }

        return execute


def discover_skills(root: Path, *, source: str = "built-in") -> list[LoadedSkill]:
    if not root.exists():
        return []
    skills = []
    for directory in sorted(path for path in root.iterdir() if path.is_dir()):
        manifest_path = directory / "SKILL.md"
        config_path = directory / "skill.json"
        if not manifest_path.is_file() or not config_path.is_file():
            continue
        skills.append(load_skill_directory(directory, source=source))
    return skills


def load_skill_directory(directory: Path, *, source: str) -> LoadedSkill:
    manifest_path = directory / "SKILL.md"
    config_path = directory / "skill.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    frontmatter, body = _parse_skill_markdown(manifest_path.read_text(encoding="utf-8"))
    skill_id = str(config.get("id") or frontmatter.get("name") or directory.name)
    dependencies = config.get("required_capabilities", [])
    if not isinstance(dependencies, list) or not all(
        isinstance(item, str) for item in dependencies
    ):
        raise ValueError("required_capabilities 必须是字符串数组")
    return LoadedSkill(
        descriptor=Capability(
            id=skill_id,
            name=str(config.get("display_name") or frontmatter.get("name") or skill_id),
            description=str(frontmatter.get("description") or config.get("description") or ""),
            kind=CapabilityKind.SKILL,
            triggers=[str(item) for item in config.get("triggers", [])],
            permissions=[str(item) for item in config.get("permissions", ["read"])],
            explicit_only=bool(config.get("explicit_only", False)),
            metadata={
                "source": source,
                "root": str(directory),
                **{
                    key: config[key]
                    for key in (
                        "role",
                        "can_own_output",
                        "output_contracts",
                        "required_capabilities",
                    )
                    if key in config
                },
                "instruction_hash": hashlib.sha256(body.encode()).hexdigest(),
            },
        ),
        instructions=body.strip(),
        root=directory,
    )


def _parse_skill_markdown(text: str) -> tuple[dict[str, str], str]:
    match = re.match(r"^---\s*\n(?P<frontmatter>.*?)\n---\s*\n(?P<body>.*)$", text, re.DOTALL)
    if match is None:
        return {}, text
    frontmatter: dict[str, str] = {}
    for line in match.group("frontmatter").splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        frontmatter[key.strip()] = value.strip().strip('"').strip("'")
    return frontmatter, match.group("body")
