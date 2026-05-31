from sqlalchemy import func, select

from app.database import SessionLocal
from app.demo import DEMO_STORE_ID
from app.models import Store


def test_store_crud(client):
    response = client.post(
        "/api/v1/stores",
        json={
            "store_name": "새 치킨집",
            "origin_info": "닭고기: 국내산",
            "is_dine_in": True,
            "is_takeout": False,
            "is_delivery": True,
        },
    )
    assert response.status_code == 201
    store_id = response.json()["id"]
    assert store_id == DEMO_STORE_ID

    response = client.get(f"/api/v1/stores/{store_id}")
    assert response.status_code == 200
    assert response.json()["store_name"] == "새 치킨집"

    response = client.put(
        f"/api/v1/stores/{store_id}",
        json={
            "store_name": "수정 치킨집",
            "origin_info": None,
            "is_dine_in": False,
            "is_takeout": True,
            "is_delivery": True,
        },
    )
    assert response.status_code == 200
    assert response.json()["store_name"] == "수정 치킨집"
    assert response.json()["is_takeout"] is True

    assert client.get("/api/v1/stores/999").status_code == 404


def test_create_store_reuses_demo_store_id(client):
    first = client.post(
        "/api/v1/stores",
        json={
            "store_name": "첫 치킨집",
            "origin_info": "닭고기: 국내산",
            "is_dine_in": True,
            "is_takeout": False,
            "is_delivery": True,
        },
    )
    second = client.post(
        "/api/v1/stores",
        json={
            "store_name": "두 번째 이름",
            "origin_info": None,
            "is_dine_in": False,
            "is_takeout": True,
            "is_delivery": True,
        },
    )

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["id"] == DEMO_STORE_ID
    assert second.json()["id"] == DEMO_STORE_ID
    assert second.json()["store_name"] == "두 번째 이름"

    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(Store)) == 1
