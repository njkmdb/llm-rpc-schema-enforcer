import json
import sys
from pathlib import Path
import pytest

from core_engine.state.db_manager import StateManager
import scripts.init_db as init_db_script
import scripts.check_db as check_db_script


def test_cli_init_db_with_default_and_custom_seed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """scripts/init_db.py의 --seed 및 --custom-seed CLI 옵션 동작 검증"""
    test_db_file = tmp_path / "cli_init_test.db"
    monkeypatch.setattr(
        init_db_script,
        "StateManager",
        lambda: StateManager(db_path=str(test_db_file)),
    )

    custom_payload = json.dumps([
        {"id": "custom_node_1", "type": "router", "attributes": {"port": 8080}, "tags": ["edge"]}
    ])

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "init_db.py",
            "--session", "cli_session_01",
            "--secret", "cli_secret_pass",
            "--seed",
            "--custom-seed", custom_payload,
        ],
    )

    init_db_script.main()
    captured = capsys.readouterr()

    assert "세션 및 비밀번호가 성공적으로 등록/검증되었습니다" in captured.out
    assert "커스텀 상태 커밋 완료" in captured.out

    # 실제 임시 DB에 커스텀 엔티티가 정상 영속화되었는지 확인
    verifier = StateManager(db_path=str(test_db_file))
    entity = verifier.get_entity("cli_session_01", "custom_node_1")
    assert entity is not None
    assert entity.type == "router"
    assert entity.attributes["port"] == 8080


def test_cli_check_db_entity_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """scripts/check_db.py를 통한 엔티티 JSON 조회 및 인증 실패 시 종료 코드 검증"""
    test_db_file = tmp_path / "cli_check_test.db"
    manager = StateManager(db_path=str(test_db_file))
    manager.verify_or_create_session("check_sess", "valid_pass")
    manager.commit_turn(
        session_id="check_sess",
        old_slot_id=None,
        new_payload={
            "entities": [
                {"id": "target_node_x", "type": "db", "attributes": {"connections": 12}, "tags": ["primary"]}
            ]
        },
    )

    monkeypatch.setattr(
        check_db_script,
        "StateManager",
        lambda: StateManager(db_path=str(test_db_file)),
    )

    # 1. 정상 비밀번호로 조회 시 엔티티 JSON 출력 확인
    monkeypatch.setattr(
        sys,
        "argv",
        ["check_db.py", "-s", "check_sess", "-t", "target_node_x", "-p", "valid_pass"],
    )
    check_db_script.main()
    out_valid = capsys.readouterr().out
    assert "target_node_x" in out_valid
    assert '"connections": 12' in out_valid

    # 2. 잘못된 비밀번호 입력 시 sys.exit(1) 호출 확인
    monkeypatch.setattr(
        sys,
        "argv",
        ["check_db.py", "-s", "check_sess", "-t", "target_node_x", "-p", "wrong_pass"],
    )
    with pytest.raises(SystemExit) as exc_info:
        check_db_script.main()
    assert exc_info.value.code == 1