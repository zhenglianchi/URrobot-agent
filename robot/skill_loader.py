import os
import re
from pathlib import Path
from typing import Dict, List, Optional
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.logger_handler import logger


class Skill:
    def __init__(self, name: str, description: str, body: str, path: str, tags: List[str] = None):
        self.name = name
        self.description = description
        self.body = body
        self.path = path
        self.tags = tags or []

    def to_dict(self) -> Dict:
        return {
            "name": self.name,
            "description": self.description,
            "body": self.body,
            "path": self.path,
            "tags": self.tags,
        }

    def get_full_content(self) -> str:
        return f'<skill name="{self.name}">\n{self.body}\n</skill>'


class SkillLoader:
    def __init__(self, skills_dir: str = None):
        if skills_dir is None:
            skills_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "skills")
        self.skills_dir = Path(skills_dir)
        self.skills: Dict[str, Skill] = {}
        self._load_all()
        logger.info(f"[SkillLoader] Loaded {len(self.skills)} skills from {self.skills_dir}")

    def _parse_frontmatter(self, text: str) -> tuple:
        match = re.match(r"^---\n(.*?)\n---\n(.*)", text, re.DOTALL)
        if not match:
            return {}, text

        meta = {}
        frontmatter = match.group(1).strip()
        
        for line in frontmatter.splitlines():
            if ":" in line:
                key, val = line.split(":", 1)
                key = key.strip()
                val = val.strip()
                
                if val.startswith("[") and val.endswith("]"):
                    items = [item.strip().strip('"').strip("'") for item in val[1:-1].split(",")]
                    meta[key] = items
                elif val.startswith('"') and val.endswith('"'):
                    meta[key] = val[1:-1]
                elif val.startswith("'") and val.endswith("'"):
                    meta[key] = val[1:-1]
                else:
                    meta[key] = val

        return meta, match.group(2).strip()

    def _load_all(self):
        if not self.skills_dir.exists():
            self.skills_dir.mkdir(parents=True, exist_ok=True)
            logger.info(f"[SkillLoader] Created skills directory: {self.skills_dir}")
            return

        for skill_file in sorted(self.skills_dir.rglob("SKILL.md")):
            try:
                text = skill_file.read_text(encoding="utf-8")
                meta, body = self._parse_frontmatter(text)
                
                name = meta.get("name", skill_file.parent.name)
                description = meta.get("description", "No description")
                tags = meta.get("tags", [])
                if isinstance(tags, str):
                    tags = [t.strip() for t in tags.split(",")]

                skill = Skill(
                    name=name,
                    description=description,
                    body=body,
                    path=str(skill_file),
                    tags=tags,
                )
                self.skills[name] = skill
                logger.debug(f"[SkillLoader] Loaded skill: {name}")

            except Exception as e:
                logger.error(f"[SkillLoader] Failed to load {skill_file}: {e}")

    def get_descriptions(self) -> str:
        if not self.skills:
            return "(no skills available)"

        lines = []
        for name, skill in self.skills.items():
            tags_str = f" [{', '.join(skill.tags)}]" if skill.tags else ""
            lines.append(f"  - {name}: {skill.description}{tags_str}")
        return "\n".join(lines)

    def get_skill(self, name: str) -> Optional[Skill]:
        return self.skills.get(name)

    def get_skill_content(self, name: str) -> str:
        skill = self.skills.get(name)
        if not skill:
            available = ", ".join(self.skills.keys()) if self.skills else "none"
            return f"Error: Unknown skill '{name}'. Available skills: {available}"
        return skill.get_full_content()

    def list_skills(self) -> List[str]:
        return list(self.skills.keys())

    def get_skills_by_tag(self, tag: str) -> List[Skill]:
        return [s for s in self.skills.values() if tag in s.tags]

    def get_skills_for_task(self, task_description: str) -> List[Skill]:
        keywords = task_description.lower()
        relevant_skills = []

        for skill in self.skills.values():
            skill_text = f"{skill.name} {skill.description} {' '.join(skill.tags)}".lower()
            if any(kw in skill_text for kw in keywords.split()):
                relevant_skills.append(skill)

        return relevant_skills

    def reload(self):
        self.skills.clear()
        self._load_all()
        logger.info(f"[SkillLoader] Reloaded {len(self.skills)} skills")


SKILL_LOADER: Optional[SkillLoader] = None


def get_skill_loader(skills_dir: str = None) -> SkillLoader:
    global SKILL_LOADER
    if SKILL_LOADER is None:
        SKILL_LOADER = SkillLoader(skills_dir)
    return SKILL_LOADER
