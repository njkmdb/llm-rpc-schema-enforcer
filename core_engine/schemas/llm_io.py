from typing import Any, Dict, List, Optional
from enum import Enum
from pydantic import BaseModel, Field

class UniversalEntity(BaseModel):
    id: str = Field(..., description="엔티티의 고유 식별자.")
    type: str = Field(..., description="데이터의 속성을 정의하는 분류 범주.")
    attributes: Dict[str, Any] = Field(default_factory=dict)
    tags: List[str] = Field(default_factory=list)

class ContextAnchor(BaseModel):
    global_flags: Dict[str, Any] = Field(default_factory=dict)
    monitored_entities: List[UniversalEntity] = Field(...)

class ActionType(str, Enum):
    UPDATE_ATTRIBUTE = "UPDATE_ATTRIBUTE"
    ADD_TAG = "ADD_TAG"
    REMOVE_TAG = "REMOVE_TAG"
    SPAWN_ENTITY = "SPAWN_ENTITY"
    ROUTE_EVENT = "ROUTE_EVENT"
    TRIGGER_PATTERN = "TRIGGER_PATTERN"

class Command(BaseModel):
    action: ActionType = Field(...)
    target_id: Optional[str] = Field(None)
    key: Optional[str] = Field(None)
    value: Optional[Any] = Field(None)

class StructuredCommand(BaseModel):
    commands: List[Command] = Field(...)