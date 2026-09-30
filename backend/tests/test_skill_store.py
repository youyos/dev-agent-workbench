import io
import zipfile

import pytest

from app.skill_store import SkillImportError, SkillStore


def _zip(files: dict[str, str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for path, content in files.items():
            archive.writestr(path, content)
    return buffer.getvalue()


def test_import_standard_skill_without_app_config(tmp_path):
    store = SkillStore(tmp_path / "skills")
    archive = _zip(
        {
            "demo/SKILL.md": (
                "---\nname: external-review\n"
                "description: Review an external document and produce findings.\n---\n"
                "Read the evidence before answering."
            ),
            "demo/references/checklist.md": "Check facts and structure.",
        }
    )

    skill, events = store.import_zip(archive)

    assert skill.descriptor.id == "external-review"
    assert skill.descriptor.metadata["source"] == "external"
    assert (store.root / "external-review" / "skill.json").is_file()
    assert events[-1]["stage"] == "skill.registered"


def test_import_rejects_path_traversal(tmp_path):
    store = SkillStore(tmp_path / "skills")
    archive = _zip(
        {
            "demo/SKILL.md": "---\nname: demo\ndescription: Safe demo skill.\n---\nDemo",
            "../escape.txt": "no",
        }
    )

    with pytest.raises(SkillImportError, match="越界路径"):
        store.import_zip(archive)

