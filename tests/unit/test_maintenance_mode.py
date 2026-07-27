from pathlib import Path

from leonaid.entrypoints.fastapi.maintenance import writes_are_blocked


def test_real_flag_file_blocks_every_write_method(tmp_path: Path) -> None:
    flag = tmp_path / "enabled"
    flag.write_text("upgrade-poc113\n", encoding="utf-8")

    for method in ("POST", "PUT", "PATCH", "DELETE"):
        assert writes_are_blocked(method, flag)


def test_reads_and_absent_flag_remain_available(tmp_path: Path) -> None:
    flag = tmp_path / "enabled"

    for method in ("GET", "HEAD", "OPTIONS"):
        assert not writes_are_blocked(method, flag)
    assert not writes_are_blocked("POST", flag)
