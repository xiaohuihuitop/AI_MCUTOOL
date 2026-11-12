"""AI:有界数据及任务中断的接口验证。"""
from mcutool.data import History, JobStore


def test_history_reports_exact_overwrite_without_consuming_other_reader():
    """AI:三个条目容量写五次，旧游标明确缺失两条。@return 无。"""
    history = History(capacity=3)
    for value in [10, 20, 30, 40, 50]:
        history.append({"value": value})
    first = history.read(0, 2)
    assert first == {"items": [{"value": 30, "cursor": 3}, {"value": 40, "cursor": 4}], "next": 4, "lost": 2}
    assert history.read(0, 2) == first
    assert history.read(4)["items"] == [{"value": 50, "cursor": 5}]


def test_backend_restart_marks_unfinished_journal_unknown(tmp_path):
    """AI:持久任务重启后保留未知，不重新执行。@param tmp_path 数据目录。@return 无。"""
    path = tmp_path / "jobs.sqlite3"
    jobs = JobStore(path)
    jobs.accept("request-a", "fingerprint", {"method": "keys.run"})
    jobs.update("request-a", state="running", action_id=42)
    jobs.close()
    recovered = JobStore(path)
    assert recovered.get("request-a")["state"] == "unknown"
    assert recovered.get("request-a")["action_id"] == 42
    recovered.close()
