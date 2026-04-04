import asyncio


class TestHealthEndpoint:
    async def test_health_returns_200(self, async_client):
        response = await async_client.get("/health")
        assert response.status_code == 200

    async def test_health_has_status_ok(self, async_client):
        response = await async_client.get("/health")
        assert response.json()["status"] == "ok"

    async def test_health_has_version(self, async_client):
        response = await async_client.get("/health")
        assert "version" in response.json()

    async def test_health_has_llm_available(self, async_client):
        response = await async_client.get("/health")
        assert "llm_available" in response.json()

    async def test_root_redirects(self, async_client):
        response = await async_client.get("/", follow_redirects=False)
        assert response.status_code in (301, 302, 307, 308)


class TestAnalysisSubmit:
    async def test_post_analyze_returns_202(self, async_client):
        payload = {
            "product_name": "iPhone 16 Pro",
            "category": "consumer electronics",
        }
        response = await async_client.post("/analyze", json=payload)
        assert response.status_code == 202

    async def test_post_analyze_returns_job_id(self, async_client):
        payload = {
            "product_name": "iPhone 16 Pro",
            "category": "consumer electronics",
        }
        response = await async_client.post("/analyze", json=payload)
        data = response.json()
        assert "job_id" in data
        assert len(data["job_id"]) > 0

    async def test_post_analyze_initial_status_pending(self, async_client):
        payload = {
            "product_name": "Nike Air Max 270",
            "category": "athletic footwear",
        }
        response = await async_client.post("/analyze", json=payload)
        assert response.json()["status"] in ("pending", "running", "completed")

    async def test_post_analyze_invalid_request_returns_422(self, async_client):
        response = await async_client.post("/analyze", json={"product_name": "x"})
        # Missing required 'category' field
        assert response.status_code == 422

    async def test_post_analyze_too_short_name_returns_422(self, async_client):
        response = await async_client.post(
            "/analyze",
            json={"product_name": "a", "category": "consumer electronics"},
        )
        assert response.status_code == 422


class TestAnalysisGet:
    async def test_get_unknown_job_returns_404(self, async_client):
        response = await async_client.get("/analyze/nonexistent-job-id-12345")
        assert response.status_code == 404

    async def test_get_job_returns_200(self, async_client):
        # Submit then retrieve
        post_response = await async_client.post(
            "/analyze",
            json={"product_name": "iPhone 16 Pro", "category": "consumer electronics"},
        )
        job_id = post_response.json()["job_id"]

        # Wait briefly for background task to complete
        for _ in range(20):
            get_response = await async_client.get(f"/analyze/{job_id}")
            if get_response.json()["status"] in ("completed", "failed"):
                break
            await asyncio.sleep(0.1)

        assert get_response.status_code == 200

    async def test_completed_job_has_report(self, async_client):
        post_response = await async_client.post(
            "/analyze",
            json={"product_name": "iPhone 16 Pro", "category": "consumer electronics"},
        )
        job_id = post_response.json()["job_id"]

        for _ in range(30):
            get_response = await async_client.get(f"/analyze/{job_id}")
            if get_response.json()["status"] == "completed":
                break
            await asyncio.sleep(0.1)

        data = get_response.json()
        assert data["status"] == "completed"
        assert data["report"] is not None

    async def test_report_has_executive_summary(self, async_client):
        post_response = await async_client.post(
            "/analyze",
            json={"product_name": "Sony WH-1000XM5", "category": "consumer electronics"},
        )
        job_id = post_response.json()["job_id"]

        for _ in range(30):
            get_response = await async_client.get(f"/analyze/{job_id}")
            if get_response.json()["status"] == "completed":
                break
            await asyncio.sleep(0.1)

        report = get_response.json()["report"]
        assert "executive_summary" in report
        assert len(report["executive_summary"]) > 20


class TestAnalysisList:
    async def test_list_returns_200(self, async_client):
        response = await async_client.get("/analyze")
        assert response.status_code == 200

    async def test_list_returns_array(self, async_client):
        response = await async_client.get("/analyze")
        assert isinstance(response.json(), list)

    async def test_list_grows_after_submit(self, async_client):
        initial = len((await async_client.get("/analyze")).json())
        await async_client.post(
            "/analyze",
            json={"product_name": "Test Widget", "category": "home appliances"},
        )
        after = len((await async_client.get("/analyze")).json())
        assert after == initial + 1
