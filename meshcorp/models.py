from __future__ import annotations
from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime
from enum import Enum
import uuid


class ProjectStatus(str, Enum):
    proposal = "proposal"
    planning = "planning"
    active = "active"
    paused = "paused"
    completed = "completed"
    killed = "killed"


class MilestoneStatus(str, Enum):
    pending = "pending"
    active = "active"
    completed = "completed"
    failed = "failed"
    skipped = "skipped"


class ActionStatus(str, Enum):
    pending = "pending"
    completed = "completed"
    dismissed = "dismissed"


class ActionUrgency(str, Enum):
    critical = "critical"
    normal = "normal"


class MessageRole(str, Enum):
    user = "user"
    participant = "participant"
    system = "system"


class RoleDefinition(BaseModel):
    title: str
    model: str
    persona: str
    skills: list[str]
    color: str = "#6b7280"
    is_lead: bool = False


class OrgTemplate(BaseModel):
    id: str
    name: str
    icon: str = "briefcase"
    description: str
    roles: list[RoleDefinition]
    default_milestones: list[str] = []
    skill_tags: list[str] = []


class Milestone(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    title: str
    description: str = ""
    deliverable: str = ""
    status: MilestoneStatus = MilestoneStatus.pending
    result: str = ""
    created_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None


class ProjectTeamMember(BaseModel):
    role: str
    model: str
    persona: str
    skills: list[str]
    color: str = "#6b7280"
    is_lead: bool = False


class Project(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    name: str
    description: str
    template_id: str
    status: ProjectStatus = ProjectStatus.planning
    team: list[ProjectTeamMember] = []
    milestones: list[Milestone] = []
    budget_allocated: float = 0.0
    budget_spent: float = 0.0
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class ConversationMessage(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    project_id: str
    milestone_id: Optional[str] = None
    role: MessageRole
    participant_name: str = ""
    participant_model: str = ""
    content: str
    skill_tags: list[str] = []
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class HumanAction(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    project_id: str
    title: str
    description: str
    urgency: ActionUrgency = ActionUrgency.normal
    status: ActionStatus = ActionStatus.pending
    blocking_milestone: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    resolved_at: Optional[datetime] = None


class CreateProjectRequest(BaseModel):
    template_id: str
    description: str = ""
    model: str = "gpt-5.2"


class ProjectResponse(BaseModel):
    project: Project
    messages: list[ConversationMessage] = []
    actions: list[HumanAction] = []


class FundProjectRequest(BaseModel):
    amount: float


class CEOMessageRequest(BaseModel):
    content: str
    directed_to: Optional[str] = None
