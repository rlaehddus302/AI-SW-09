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

