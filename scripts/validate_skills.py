"""Validate the portable skill manifests shipped by Open Claude Design."""

from __future__ import annotations

import re
from pathlib import Path

import yaml

ALLOWED_FRONTMATTER_KEYS = frozenset({"name", "description", "license", "allowed-tools", "metadata"})
NAME_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
FRONTMATTER_PATTERN = re.compile(r"^---\n(.*?)\n---", re.DOTALL)


def _mapping(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must contain a YAML mapping")
    return {str(key): item for key, item in value.items()}


def validate_skill(skill_dir: Path) -> list[str]:
    """Return validation errors for one canonical skill directory."""
    errors: list[str] = []
    skill_file = skill_dir / "SKILL.md"
    try:
        content = skill_file.read_text(encoding="utf-8")
    except OSError as error:
        return [f"{skill_file}: {error}"]

    frontmatter_match = FRONTMATTER_PATTERN.match(content)
    if frontmatter_match is None:
        return [f"{skill_file}: missing or malformed YAML frontmatter"]
    try:
        frontmatter = _mapping(yaml.safe_load(frontmatter_match.group(1)), str(skill_file))
    except (ValueError, yaml.YAMLError) as error:
        return [str(error)]

    unexpected = sorted(set(frontmatter) - ALLOWED_FRONTMATTER_KEYS)
    if unexpected:
        errors.append(f"{skill_file}: unsupported frontmatter keys: {', '.join(unexpected)}")

    name = frontmatter.get("name")
    if not isinstance(name, str) or NAME_PATTERN.fullmatch(name) is None:
        errors.append(f"{skill_file}: name must use lowercase hyphen-case")
    elif name != skill_dir.name:
        errors.append(f"{skill_file}: name must match directory '{skill_dir.name}'")

    description = frontmatter.get("description")
    if not isinstance(description, str) or not description.strip():
        errors.append(f"{skill_file}: description must be a non-empty string")
    elif len(description) > 1024 or "<" in description or ">" in description:
        errors.append(f"{skill_file}: description violates Agent Skills constraints")

    metadata_file = skill_dir / "agents" / "openai.yaml"
    try:
        metadata = _mapping(yaml.safe_load(metadata_file.read_text(encoding="utf-8")), str(metadata_file))
        policy = _mapping(metadata.get("policy"), f"{metadata_file}: policy")
    except (OSError, ValueError, yaml.YAMLError) as error:
        errors.append(str(error))
    else:
        if policy.get("allow_implicit_invocation") is not True:
            errors.append(f"{metadata_file}: implicit invocation must remain enabled")

    if "[TODO:" in content:
        errors.append(f"{skill_file}: unresolved TODO placeholder")
    return errors


def main() -> int:
    """Validate every canonical skill and print a compact result."""
    skills_root = Path(__file__).parents[1] / "skills"
    skill_dirs = sorted(path for path in skills_root.iterdir() if path.is_dir())
    errors = [error for skill_dir in skill_dirs for error in validate_skill(skill_dir)]
    if errors:
        print("\n".join(errors))
        return 1
    print(f"Validated {len(skill_dirs)} skills.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
