from model import props as props_module
from model.props import PropsModel


def test_get_by_name_fetches_one_matching_prop(monkeypatch):
    calls = []

    def fake_execute_query(sql, params=None, fetch_one=False, fetch_all=False):
        calls.append({
            "params": params,
            "fetch_one": fetch_one,
            "fetch_all": fetch_all,
        })
        if not fetch_one:
            return None
        return {
            "id": 6867,
            "world_id": 9,
            "name": "笔记本大别墅计划",
            "content": "",
            "reference_image": "https://cdn.test/notebook.png",
            "other_info": None,
            "user_id": 1,
            "create_time": None,
            "update_time": None,
        }

    monkeypatch.setattr(props_module, "execute_query", fake_execute_query)

    prop = PropsModel.get_by_name(9, "笔记本大别墅计划")

    assert prop is not None
    assert prop.id == 6867
    assert prop.reference_image == "https://cdn.test/notebook.png"
    assert calls == [{
        "params": (9, "笔记本大别墅计划"),
        "fetch_one": True,
        "fetch_all": False,
    }]
