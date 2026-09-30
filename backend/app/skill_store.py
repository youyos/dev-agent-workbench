from __future__ import annotations

import json
import re
import shutil
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

from .skill_loader import LoadedSkill, _parse_skill_markdown, load_skill_directory

MAX_SKILL_ARCHIVE_BYTES = 10 * 1024 * 1024
MAX_SKILL_FILES = 200
MAX_SKILL_FILE_BYTES = 2 * 1024 * 1024


class SkillImportError(ValueError):
    pass


class SkillStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def list(self) -> list[LoadedSkill]:
        skills = []
        for directory in sorted(path for path in self.root.iterdir() if path.is_dir()):
            if (directory / "SKILL.md").is_file() and (directory / "skill.json").is_file():
                skills.append(load_skill_directory(directory, source="external"))
        return skills

    def import_zip(self, archive: bytes) -> tuple[LoadedSkill, list[dict[str, str]]]:
        if not archive:
            raise SkillImportError("上传文件为空")
        if len(archive) > MAX_SKILL_ARCHIVE_BYTES:
            raise SkillImportError("Skill ZIP 超过 10 MB")

        events = [{"stage": "archive.received", "message": "已接收 Skill ZIP"}]
        with tempfile.TemporaryDirectory(prefix="skill-import-") as temp_dir:
            staging = Path(temp_dir)
            archive_path = staging / "skill.zip"
            archive_path.write_bytes(archive)
            try:
                zip_file = zipfile.ZipFile(archive_path)
            except zipfile.BadZipFile as exc:
                raise SkillImportError("文件不是有效的 ZIP") from exc

            files = [item for item in zip_file.infolist() if not item.is_dir()]
            if len(files) > MAX_SKILL_FILES:
                raise SkillImportError(f"Skill 文件数量超过 {MAX_SKILL_FILES}")
            total_size = 0
            extract_root = staging / "extracted"
            extract_root.mkdir()
            for item in files:
                path = PurePosixPath(item.filename)
                if path.is_absolute() or ".." in path.parts:
                    raise SkillImportError(f"ZIP 包含越界路径：{item.filename}")
                if item.file_size > MAX_SKILL_FILE_BYTES:
                    raise SkillImportError(f"单个文件超过 2 MB：{item.filename}")
                if (item.external_attr >> 16) & 0o170000 == 0o120000:
                    raise SkillImportError(f"ZIP 不允许符号链接：{item.filename}")
                total_size += item.file_size
                if total_size > MAX_SKILL_ARCHIVE_BYTES:
                    raise SkillImportError("Skill 解压后超过 10 MB")
                target = extract_root.joinpath(*path.parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(zip_file.read(item))
            events.append({"stage": "archive.validated", "message": f"已安全解压 {len(files)} 个文件"})

            manifests = [
                path
                for path in extract_root.rglob("SKILL.md")
                if "__MACOSX" not in path.parts
            ]
            if len(manifests) != 1:
                raise SkillImportError("ZIP 必须且只能包含一个 SKILL.md")
            skill_root = manifests[0].parent
            frontmatter, _ = _parse_skill_markdown(manifests[0].read_text(encoding="utf-8"))
            skill_id = _normalize_skill_id(frontmatter.get("name") or skill_root.name)
            if not skill_id:
                raise SkillImportError("SKILL.md 缺少有效的 name")
            config_path = skill_root / "skill.json"
            if not config_path.exists():
                description = frontmatter.get("description", "")
                config_path.write_text(
                    json.dumps(
                        {
                            "id": skill_id,
                            "display_name": frontmatter.get("name") or skill_id,
                            "triggers": _default_triggers(frontmatter.get("name", ""), description),
                            "permissions": ["read"],
                        },
                        ensure_ascii=False,
                        indent=2,
                    ),
                    encoding="utf-8",
                )
            provisional = load_skill_directory(skill_root, source="external")
            destination = self.root / provisional.descriptor.id
            if destination.exists():
                raise SkillImportError(f"Skill 已存在：{provisional.descriptor.id}")
            shutil.copytree(skill_root, destination)

        loaded = load_skill_directory(destination, source="external")
        events.append({"stage": "skill.registered", "message": f"已注册 {loaded.descriptor.name}"})
        return loaded, events


def _normalize_skill_id(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9-]+", "-", value.strip().lower().replace("_", "-"))
    return normalized.strip("-")[:80]


def _default_triggers(name: str, description: str) -> list[str]:
    terms = re.findall(r"[a-zA-Z0-9_-]{2,}|[\u4e00-\u9fff]{2,}", f"{name} {description}")
    return list(dict.fromkeys(terms))[:12]

