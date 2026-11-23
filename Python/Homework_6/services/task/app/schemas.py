from datetime import datetime
from enum import StrEnum
from pydantic import BaseModel, ConfigDict, Field


class Priority(StrEnum):
    low = "low"
    medium = "medium"
    high = "high"
    critical = "critical"


class Status(StrEnum):
    new = "new"
    in_progress = "in_progress"
    on_review = "on_review"
    done = "done"
    rejected = "rejected"


class DepartmentCreate(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    code: str = Field(min_length=2, max_length=20, pattern=r"^[A-Za-z][A-Za-z0-9_-]*$")


class EmployeeCreate(BaseModel):
    login: str = Field(min_length=3, max_length=50, pattern=r"^[A-Za-z][A-Za-z0-9_.-]*$")
    full_name: str = Field(min_length=2, max_length=120)
    password: str = Field(min_length=8, max_length=128)
    department_id: int = Field(gt=0)
    role: str = Field(default="employee", pattern=r"^(employee|manager|admin)$")


class LoginRequest(BaseModel):
    login: str
    password: str


class TaskCreate(BaseModel):
    title: str = Field(min_length=3, max_length=200)
    description: str = Field(default="", max_length=10000)
    to_department: int = Field(gt=0)
    assignee: int | None = Field(default=None, gt=0)
    priority: Priority = Priority.medium
    deadline: datetime | None = None


class TaskPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str | None = Field(default=None, min_length=3, max_length=200)
    description: str | None = Field(default=None, max_length=10000)
    priority: Priority | None = None
    deadline: datetime | None = None


class StatusChange(BaseModel):
    status: Status
    comment: str | None = Field(default=None, max_length=4000)


class TaskTransfer(BaseModel):
    to_department: int = Field(gt=0)
    assignee: int | None = Field(default=None, gt=0)
    comment: str = Field(min_length=3, max_length=4000)


class CommentCreate(BaseModel):
    text: str = Field(min_length=1, max_length=4000)


class AssignManager(BaseModel):
    manager_id: int = Field(gt=0)


class EmployeeState(BaseModel):
    is_active: bool
