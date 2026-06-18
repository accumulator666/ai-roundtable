import os
import json
from meshcorp.models import OrgTemplate

TEMPLATES: dict[str, OrgTemplate] = {}
TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "templates")


def load_templates():
    global TEMPLATES
    TEMPLATES.clear()
    for filename in os.listdir(TEMPLATE_DIR):
        if not filename.endswith(".json"):
            continue
        filepath = os.path.join(TEMPLATE_DIR, filename)
        with open(filepath) as f:
            data = json.load(f)
        template = OrgTemplate(**data)
        TEMPLATES[template.id] = template


def get_template(template_id: str) -> OrgTemplate | None:
    return TEMPLATES.get(template_id)


def list_templates() -> list[OrgTemplate]:
    return list(TEMPLATES.values())
