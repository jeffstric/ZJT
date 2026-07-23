import contextlib

import pytest

from services import storyboard_batch_operation_service as service


@contextlib.contextmanager
def _fake_transaction():
    yield object()


def test_batch_delete_is_atomic_and_settles_generation_items(monkeypatch):
    updates = []
    monkeypatch.setattr(service, "transaction", _fake_transaction)
    monkeypatch.setattr(
        service,
        "execute_query_in_transaction",
        lambda conn, sql, params=None: [{"id": 11}, {"id": 12}],
    )

    def fake_update(conn, sql, params=None):
        updates.append((sql, params))
        return 3 if "storyboard_image_batch_item" in sql else 2

    monkeypatch.setattr(service, "execute_update_in_transaction", fake_update)

    result = service.batch_delete_storyboard_scenes(22, [12, 11, 12])

    assert result["deleted_scene_ids"] == [11, 12]
    assert result["deleted_count"] == 2
    assert result["settled_batch_item_count"] == 3
    assert len(updates) == 2


def test_batch_delete_rejects_stale_selection_before_writes(monkeypatch):
    writes = []
    monkeypatch.setattr(service, "transaction", _fake_transaction)
    monkeypatch.setattr(
        service,
        "execute_query_in_transaction",
        lambda conn, sql, params=None: [{"id": 11}],
    )
    monkeypatch.setattr(
        service,
        "execute_update_in_transaction",
        lambda *args, **kwargs: writes.append((args, kwargs)),
    )

    with pytest.raises(service.StoryboardBatchOperationError) as exc_info:
        service.batch_delete_storyboard_scenes(22, [11, 12])

    assert exc_info.value.error_code == "selection_stale"
    assert writes == []
