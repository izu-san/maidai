from rino_agent.storage import ensure_private_directory


def test_private_storage_directory_is_created(tmp_path):
    target = tmp_path / "private"
    assert ensure_private_directory(target) == target
    assert target.is_dir()
