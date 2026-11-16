from pathlib import Path

import pytest
from conftest import PUBLIC_URL, git
from fastapi.testclient import TestClient

from patchwork.api.repositories import git_client_type
from patchwork.config import Settings
from patchwork.ingestion.git import GitClient
from patchwork.main import create_app
from patchwork.schemas.errors import ErrorResponse
from patchwork.schemas.repositories import ImportResponse, SearchResponse


@pytest.fixture
def api(settings: Settings, client_type: type[GitClient]):
    app = create_app(settings)
    app.dependency_overrides[git_client_type] = lambda: client_type
    with TestClient(app) as client:
        yield client


def import_fixture(api: TestClient, commit: str | None = None) -> str:
    body: dict[str, str] = {"url": PUBLIC_URL}
    if commit:
        body["commit_sha"] = commit
    response = api.post("/api/repositories", json=body)
    assert response.status_code == 201, response.text
    result = ImportResponse.model_validate(response.json())
    assert result.repository.status == "ready"
    return result.repository.id


def test_api_import_idempotency_metadata_and_proxy_alias(
    api: TestClient, local_repo: tuple[Path, str, str]
) -> None:
    identifier = import_fixture(api, local_repo[1])
    repeat = api.post(
        "/repositories", json={"url": PUBLIC_URL + ".git", "commit_sha": local_repo[1].upper()}
    )
    assert repeat.status_code == 200 and repeat.json()["reused"]
    assert repeat.json()["repository"]["id"] == identifier
    listing = api.get("/api/repositories").json()
    assert listing["total"] == 1 and listing["items"][0]["id"] == identifier
    detail = api.get(f"/api/repositories/{identifier}")
    assert detail.status_code == 200
    assert detail.json()["commit_sha"] == local_repo[1]
    assert "snapshot_name" not in detail.json() and "lease_token" not in detail.json()
    files = api.get(f"/api/repositories/{identifier}/files").json()
    assert files["items"][0]["path"] == "main.py"
    assert len(files["items"][0]["content_hash"]) == 64
    assert "source" not in files["items"][0]
    assert api.get("/health").json()["status"] == "ok"


def test_search_ranking_locations_and_literals(
    api: TestClient, local_repo: tuple[Path, str, str]
) -> None:
    root = local_repo[0]
    (root / "search.py").write_text("""import os
class Holder:
    def target(self):
        return "body"
def target_more():
    pass
def before_target():
    pass
# target in source
# literal [.*] and %_ are not operators
""")
    (root / "target_notes.py").write_text("# notes\n")
    git(root, "add", ".")
    git(root, "commit", "-m", "Search cases")
    identifier = import_fixture(api)
    response = api.get(
        f"/api/repositories/{identifier}/search", params={"q": "TARGET", "limit": 100}
    )
    assert response.status_code == 200
    result = SearchResponse.model_validate(response.json())
    assert result.results[0].name == "target"
    assert result.results[0].qualified_name == "Holder.target"
    assert result.results[0].start_line == 3
    assert result.results[0].snippet.strip() == "def target(self):"
    assert [hit.rank for hit in result.results] == sorted(hit.rank for hit in result.results)
    assert {hit.kind for hit in result.results} == {"symbol", "path", "text"}
    assert {hit.rank for hit in result.results} >= {0, 1, 2, 4, 6}
    assert (
        api.get(f"/api/repositories/{identifier}/search", params={"q": "[.*]"}).json()["results"][
            0
        ]["start_line"]
        == 10
    )
    assert (
        api.get(f"/api/repositories/{identifier}/search", params={"q": "%_"}).json()["results"][0][
            "kind"
        ]
        == "text"
    )
    assert (
        api.get(f"/api/repositories/{identifier}/search", params={"q": "absent"}).json()["results"]
        == []
    )
    assert (
        api.get(
            f"/api/repositories/{identifier}/search", params={"q": "TARGET", "limit": 100}
        ).json()
        == response.json()
    )


def test_exact_symbol_missing_symbols_and_commit_filter(
    api: TestClient, local_repo: tuple[Path, str, str]
) -> None:
    identifier = import_fixture(api, local_repo[1])
    base = f"/api/repositories/{identifier}"
    exact = api.get(base + "/symbols", params={"name": "original"}).json()
    assert exact["total"] == 1 and exact["items"][0]["kind"] == "function"
    assert api.get(base + "/symbols", params={"name": "Original"}).json()["items"] == []
    assert api.get(base + "/symbols", params={"name": "ORIG", "exact": False}).json()["total"] == 1
    assert api.get(base + "/symbols", params={"name": "missing"}).json()["items"] == []
    assert api.get(base + "/search", params={"q": "updated"}).json()["results"] == []
    assert (
        api.get(base + "/search", params={"q": "original", "commit_sha": local_repo[2]}).status_code
        == 404
    )
    assert api.get(base + "/symbols", params={"commit_sha": local_repo[1]}).status_code == 200
    assert api.get(base + "/symbols", params={"commit_sha": "main"}).status_code == 422


def test_configured_result_and_snippet_limits(
    settings: Settings, client_type: type[GitClient], local_repo: tuple[Path, str, str]
) -> None:
    root = local_repo[0]
    (root / "long.py").write_text(
        "# " + "ß" * 200 + " café " + "x" * 200 + "\n# café again\n", encoding="utf-8"
    )
    git(root, "add", ".")
    git(root, "commit", "-m", "Long Unicode line")
    app = create_app(settings.model_copy(update={"max_results": 1, "max_snippet_chars": 40}))
    app.dependency_overrides[git_client_type] = lambda: client_type
    with TestClient(app) as client:
        identifier = import_fixture(client)
        result = client.get(
            f"/api/repositories/{identifier}/search", params={"q": "CAFÉ", "limit": 100}
        ).json()
        assert result["limit"] == 1 and len(result["results"]) == 1 and result["truncated"]
        assert len(result["results"][0]["snippet"]) <= 40
        assert "café" in result["results"][0]["snippet"]
        page = client.get(
            f"/api/repositories/{identifier}/symbols", params={"limit": 100, "offset": 1}
        ).json()
        assert page["limit"] == 1 and page["offset"] == 1 and len(page["items"]) == 1
        assert client.get("/api/repositories", params={"offset": 100}).json()["items"] == []


def test_import_metadata_and_malformed_source(
    api: TestClient, local_repo: tuple[Path, str, str]
) -> None:
    root = local_repo[0]
    (root / "imports.py").write_text("from ..package import name as alias\n")
    (root / "broken.py").write_text("def broken(:\n pass\n")
    git(root, "add", ".")
    git(root, "commit", "-m", "Import and malformed source")
    identifier = import_fixture(api)
    imports = api.get(f"/api/repositories/{identifier}/imports").json()
    assert imports["total"] == 1
    assert imports["items"][0]["relative_level"] == 2
    assert imports["items"][0]["module_name"] == "package"
    assert imports["items"][0]["alias"] == "alias"
    files = api.get(f"/api/repositories/{identifier}/files").json()
    assert next(file for file in files["items"] if file["path"] == "broken.py")["has_errors"]


@pytest.mark.parametrize(
    "body",
    [
        {"url": "file:///tmp/repo"},
        {"url": PUBLIC_URL, "commit_sha": "main"},
        {"url": PUBLIC_URL, "commit_sha": "g" * 40},
        {"url": PUBLIC_URL, "extra": True},
        {},
    ],
)
def test_validation_contract(api: TestClient, body: dict[str, object]) -> None:
    response = api.post("/api/repositories", json=body)
    assert response.status_code == 422
    error = ErrorResponse.model_validate(response.json()).error
    assert error.code == "validation_error" and error.details
    assert api.get("/api/repositories").json()["total"] == 0


def test_failure_status_and_consistent_errors(api: TestClient, settings: Settings) -> None:
    response = api.post("/api/repositories", json={"url": PUBLIC_URL, "commit_sha": "0" * 40})
    assert response.status_code == 422
    error = ErrorResponse.model_validate(response.json()).error
    assert error.code == "invalid_revision" and error.repository_id
    assert str(settings.repository_dir) not in response.text
    failed = api.get(f"/api/repositories/{error.repository_id}").json()
    assert failed["status"] == "failed" and failed["error_code"] == "invalid_revision"
    assert (
        api.get(f"/api/repositories/{error.repository_id}/search", params={"q": "x"}).status_code
        == 409
    )
    missing = api.get("/api/repositories/" + "a" * 64)
    assert missing.status_code == 404
    assert ErrorResponse.model_validate(missing.json()).error.code == "repository_not_found"
    assert api.get("/api/repositories/invalid").status_code == 422
    assert api.get("/api/repositories", params={"limit": 0}).status_code == 422
    assert api.get("/api/repositories", params={"limit": 501}).status_code == 422
    assert api.get("/api/repositories", params={"offset": -1}).status_code == 422


def test_empty_query_is_rejected(api: TestClient) -> None:
    identifier = import_fixture(api)
    for query in ("", "   ", "x" * 201):
        assert (
            api.get(f"/api/repositories/{identifier}/search", params={"q": query}).status_code
            == 422
        )


def test_openapi_and_database_unavailability(api: TestClient, settings: Settings) -> None:
    schema = api.get("/openapi.json").json()
    assert "/api/repositories/{identifier}/search" in schema["paths"]
    assert "/repositories" not in schema["paths"]
    post = schema["paths"]["/api/repositories"]["post"]
    assert {"200", "201", "409", "413", "422", "502", "503", "504"} <= set(post["responses"])
    settings.database_path.unlink()
    response = api.get("/api/repositories")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "storage_unavailable"
    assert not settings.database_path.exists()
