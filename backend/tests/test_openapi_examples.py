def test_openapi_contains_response_examples(client):
    response = client.get("/openapi.json")

    assert response.status_code == 200
    schema = response.json()

    create_store = schema["paths"]["/api/v1/stores"]["post"]["responses"]
    assert create_store["201"]["content"]["application/json"]["example"]["id"] == 1
    assert create_store["422"]["content"]["application/json"]["example"]["detail"][0]["loc"]

    analyze = schema["paths"]["/api/v1/stores/{store_id}/reviews/analyze"]["post"]["responses"]
    assert analyze["202"]["content"]["application/json"]["example"]["task_id"].startswith("task_")
    assert analyze["409"]["content"]["application/json"]["example"]["detail"]["invalid_reviews"][0]["id"] == 3

    approve = schema["paths"]["/api/v1/stores/{store_id}/reviews/{review_id}/approve"]["post"]["responses"]
    assert approve["200"]["content"]["application/json"]["example"]["status"] == "approved"
    assert approve["404"]["content"]["application/json"]["example"]["detail"] == "리뷰를 찾을 수 없습니다."


def test_openapi_contains_schema_examples(client):
    response = client.get("/openapi.json")

    assert response.status_code == 200
    components = response.json()["components"]["schemas"]

    assert components["StoreCreate"]["example"]["store_name"] == "민트치킨 성수점"
    assert components["BatchReviewRequest"]["example"]["review_ids"] == [2, 3, 4]
    assert components["ReviewDetail"]["example"]["rag_references"][0]["similarity"] == 0.87
