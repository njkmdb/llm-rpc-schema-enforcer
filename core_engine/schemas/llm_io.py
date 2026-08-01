from typing import Any, Dict, List, Optional
from enum import Enum
from pydantic import BaseModel, Field
from typing import Literal

AllowedEntityID = Literal[
    "master_node_01", "worker_node_a", "worker_node_b", "proxy_gateway", 
    "firewall_module", "database_cluster", "auth_server", "cache_redis", "message_queue"
]

AllowedTags = Literal[
    "active", "standby", "compromised", "secure", "load_balanced", 
    "high_priority", "deprecated", "anomaly"
]

class Position(BaseModel):
    x: int = Field(..., ge=0, le=15, description="그리드 X 좌표 (0-15 제한)")
    y: int = Field(..., ge=0, le=15, description="그리드 Y 좌표 (0-15 제한)")

class DynamicEntity(BaseModel):
    id: AllowedEntityID
    type: Literal["module", "node"]
    attributes: Dict[str, Any] = Field(default_factory=dict)
    tags: List[AllowedTags] = Field(default_factory=list)
    position: Position

class InfrastructureProvisioningOutput(BaseModel):
    """LLM이 분석을 마치고 시스템에 반환하는 최종 동적 인프라 배포 배열"""
    dynamic_entities: List[DynamicEntity] = Field(..., description="동적으로 배포할 컨테이너/노드 인스턴스 배열")

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
    DESTROY_ENTITY = "DESTROY_ENTITY"
    ROUTE_EVENT = "ROUTE_EVENT"
    TRIGGER_PATTERN = "TRIGGER_PATTERN"

class Command(BaseModel):
    action: ActionType = Field(...)
    target_id: Optional[str] = Field(None)
    key: Optional[str] = Field(None)
    value: Optional[Any] = Field(None)

class StructuredCommand(BaseModel):
    commands: List[Command] = Field(...)