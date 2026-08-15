import logging
from typing import List, Dict, Any, Tuple
from core_engine.schemas.llm_io import UniversalEntity, StructuredCommand, Command, ActionType
from core_engine.state.db_manager import StateManager

logger = logging.getLogger("LRSE_VM")
logger.setLevel(logging.INFO)

class VMInterpreter:
    def __init__(self, state_manager: StateManager):
        self.state_manager = state_manager

    def execute(self, session_id: str, structured_command: StructuredCommand) -> Tuple[List[Dict[str, Any]], List[UniversalEntity]]:
        execution_report = []
        modified_entities = {} 

        for cmd in structured_command.commands:
            report_entry = {
                "command": cmd.model_dump(),
                "status": "pending",
                "message": ""
            }

            try:
                # 💡 1. [옵션 A 적용] 엔티티 생성(SPAWN)은 DB 조회 전에 예외적으로 선처리
                if cmd.action == ActionType.SPAWN_ENTITY:
                    if not cmd.target_id:
                        raise ValueError("SPAWN_ENTITY requires a target_id.")
                    
                    # 이미 세션 내에 존재하는지 방어
                    if cmd.target_id in modified_entities or self.state_manager.get_entity(session_id, cmd.target_id):
                        raise ValueError(f"EntityAlreadyExists: ID '{cmd.target_id}' already exists in this session.")
                    
                    self._handle_spawn_entity(modified_entities, cmd)
                    
                    report_entry["status"] = "success"
                    report_entry["message"] = f"Successfully spawned new entity: {cmd.target_id}"
                    execution_report.append(report_entry)
                    continue # 생성 완료 후 다음 명령어로 즉시 이동

                # 2. 기존 엔티티 조회 로직 (SPAWN 이외의 액션들)
                if cmd.target_id not in modified_entities:
                    entity = self.state_manager.get_entity(session_id, cmd.target_id)
                    if not entity:
                        raise ValueError(f"EntityNotFound: ID '{cmd.target_id}' does not exist in the current context.")
                    modified_entities[cmd.target_id] = entity

                entity = modified_entities[cmd.target_id]

                # 3. 기존 엔티티 조작 액션 라우팅
                if cmd.action == ActionType.UPDATE_ATTRIBUTE:
                    self._handle_update_attribute(entity, cmd)
                elif cmd.action == ActionType.ADD_TAG:
                    self._handle_add_tag(entity, cmd)
                elif cmd.action == ActionType.REMOVE_TAG:
                    self._handle_remove_tag(entity, cmd)
                else:
                    raise ValueError(f"Unsupported or Unknown ActionType: {cmd.action}")

                report_entry["status"] = "success"
                report_entry["message"] = f"Executed {cmd.action.value} on {cmd.target_id}"

            except Exception as e:
                report_entry["status"] = "failed"
                report_entry["message"] = str(e)
                logger.warning(f"Command execution skipped due to exception: {e} | Command: {cmd.model_dump()}")

            execution_report.append(report_entry)

        return execution_report, list(modified_entities.values())

    def _handle_spawn_entity(self, modified_entities: Dict[str, UniversalEntity], cmd: Command):
        """SPAWN_ENTITY 명령어 처리기: cmd.value에서 초기 데이터를 추출하여 새 엔티티를 생성합니다."""
        # cmd.value가 딕셔너리로 들어왔을 때 속성을 추출, 없으면 빈 값으로 안전하게 초기화
        init_data = cmd.value if isinstance(cmd.value, dict) else {}
        
        new_entity = UniversalEntity(
            id=cmd.target_id,
            type=init_data.get("type", "default_type"),
            attributes=init_data.get("attributes", {}),
            tags=init_data.get("tags", [])
        )
        modified_entities[cmd.target_id] = new_entity

    def _handle_update_attribute(self, entity: UniversalEntity, cmd: Command):
        current_value = entity.attributes.get(cmd.key)
        if isinstance(cmd.value, (int, float)) and isinstance(current_value, (int, float)):
            entity.attributes[cmd.key] = current_value + cmd.value
        else:
            entity.attributes[cmd.key] = cmd.value

    def _handle_add_tag(self, entity: UniversalEntity, cmd: Command):
        # LLM이 태그명을 value에 넣든 key에 넣든 유연하게 캐치하도록 수정
        target_tag = str(cmd.value if cmd.value is not None else cmd.key)
        if target_tag not in entity.tags and target_tag != "None":
            entity.tags.append(target_tag)

    def _handle_remove_tag(self, entity: UniversalEntity, cmd: Command):
        # 제거 시에도 동일하게 유연한 파싱 적용
        target_tag = str(cmd.value if cmd.value is not None else cmd.key)
        if target_tag in entity.tags:
            entity.tags.remove(target_tag)