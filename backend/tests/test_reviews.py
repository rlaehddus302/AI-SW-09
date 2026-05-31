def test_list_reviews_filters_and_pagination(client, seeded_store):
    response = client.get(
        f"/api/v1/stores/{seeded_store}/reviews",
        params={"order_type": "delivery", "page": 1, "size": 2},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 3
    assert body["page"] == 1
    assert body["size"] == 2
    assert len(body["reviews"]) == 2

    response = client.get(
        f"/api/v1/stores/{seeded_store}/reviews",
        params={"status": "needs_approval", "sentiment": "negative"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["reviews"][0]["status"] == "needs_approval"


def test_review_detail_parses_json_fields(client, seeded_store):
    response = client.get(f"/api/v1/stores/{seeded_store}/reviews/4")
    assert response.status_code == 200
    body = response.json()
    assert body["interpretation"]["core_issue"] == "위생 이슈"
    assert body["rag_references"][0]["similarity"] == 0.9


def test_review_stats_counts_distributions(client, seeded_store):
    response = client.get(f"/api/v1/stores/{seeded_store}/reviews/stats")
    assert response.status_code == 200
    body = response.json()
    assert body["total_reviews"] == 5
    assert body["sentiment_distribution"]["positive"] == 1
    assert body["sentiment_distribution"]["negative"] == 2
    assert body["risk_distribution"]["high"] == 2
    assert body["status_distribution"]["pending"] == 1
    assert body["status_distribution"]["needs_approval"] == 1
    assert body["sub_type_distribution"]["배달지연"] == 1


def test_review_404_and_query_422(client, seeded_store):
    assert client.get("/api/v1/stores/999/reviews").status_code == 404
    assert client.get(f"/api/v1/stores/{seeded_store}/reviews/999").status_code == 404
    assert client.get(
        f"/api/v1/stores/{seeded_store}/reviews",
        params={"order_type": "invalid"},
    ).status_code == 422

