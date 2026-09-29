import json
from concurrent.futures import ThreadPoolExecutor

from rino_agent.audit import AgentAuditLog


def test_audit_redacts_secrets_and_chains_records(tmp_path):
    log = AgentAuditLog(tmp_path / "audit.jsonl", "test-key")
    log.write("agent.run", authorization="hidden", nested={"device_id": "hidden", "safe": "ok"})
    log.write("agent.approve", token="hidden")
    records = [json.loads(line) for line in (tmp_path / "audit.jsonl").read_text(encoding="utf-8").splitlines()]
    assert records[0]["data"]["authorization"] == "[REDACTED]"
    assert records[0]["data"]["nested"]["device_id"] == "[REDACTED]"
    assert records[1]["previous_hash"] == records[0]["record_hash"]
    assert log.verify() is True


def test_audit_verification_detects_tampering(tmp_path):
    path = tmp_path / "audit.jsonl"
    log = AgentAuditLog(path, "test-key")
    log.write("agent.run", safe="value")
    path.write_text(path.read_text(encoding="utf-8").replace("value", "altered"), encoding="utf-8")
    assert log.verify() is False


def test_audit_chain_remains_valid_for_concurrent_writes(tmp_path):
    log = AgentAuditLog(tmp_path / "audit.jsonl", "test-key")
    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(lambda index: log.write("tool.executed", index=index), range(32)))
    assert log.verify() is True
