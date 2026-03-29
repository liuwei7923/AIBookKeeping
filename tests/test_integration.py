import os
import socket
import subprocess
import time
from pathlib import Path

import httpx
import pytest


def get_free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture
def running_server(tmp_path: Path):
    memory_path = tmp_path / "categorization_memory.json"
    port = get_free_port()
    base_url = f"http://127.0.0.1:{port}"

    env = os.environ.copy()
    env["CATEGORIZATION_MEMORY_PATH"] = str(memory_path)

    process = subprocess.Popen(
        [
            str(Path(".venv/bin/python")),
            "-m",
            "uvicorn",
            "main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        cwd=Path(__file__).resolve().parents[1],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    for _ in range(50):
        try:
            response = httpx.get(f"{base_url}/health", timeout=1.0)
            if response.status_code == 200:
                yield base_url
                break
        except httpx.HTTPError:
            time.sleep(0.1)
    else:
        process.terminate()
        stdout, stderr = process.communicate(timeout=5)
        raise RuntimeError(f"Server did not start.\nSTDOUT:\n{stdout}\nSTDERR:\n{stderr}")

    process.terminate()
    process.wait(timeout=5)


def test_memory_endpoints_over_live_server(running_server: str) -> None:
    csv_path = Path("/Users/w_liu/Downloads/short_transaction.csv")
    assert csv_path.exists(), "Expected sample CSV fixture to exist"

    with csv_path.open("rb") as file_handle:
        import_response = httpx.post(
            f"{running_server}/categorization-memory/import",
            files={"file": ("short_transaction.csv", file_handle, "text/csv")},
            timeout=10.0,
        )

    assert import_response.status_code == 200
    assert import_response.json() == {"imported": 14, "skipped": 0}

    memory_response = httpx.get(f"{running_server}/categorization-memory", timeout=10.0)
    assert memory_response.status_code == 200

    memory_items = memory_response.json()
    assert len(memory_items) == 14
    assert memory_items[0]["merchant"] == "Navia Benefit Solutions"
    assert memory_items[0]["corrected_category"] == "Other Income"
