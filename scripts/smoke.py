"""Actual loopback HTTP + Streamlit runtime check. Never calls real financial providers."""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import httpx


def wait_for(url: str):
    for _ in range(60):
        try:
            result = httpx.get(url, timeout=2)
            if result.status_code == 200:
                return result
        except httpx.HTTPError:
            pass
        time.sleep(0.5)
    raise RuntimeError(f"local service did not start: {url}")


def main():
    env = {**os.environ, "FINSIGHT_MODE": "mock", "FINSIGHT_API_URL": "http://127.0.0.1:18000"}
    processes = []
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    Path("data").mkdir(exist_ok=True)
    try:
        with Path("data/smoke-server.log").open("w", encoding="utf-8") as log:
            for args in [
                ["-m", "uvicorn", "finsight.api:app", "--host", "127.0.0.1", "--port", "18000"],
                [
                    "-m",
                    "streamlit",
                    "run",
                    "ui/app.py",
                    "--server.address",
                    "127.0.0.1",
                    "--server.port",
                    "18501",
                    "--server.headless",
                    "true",
                    "--browser.gatherUsageStats",
                    "false",
                ],
            ]:
                processes.append(
                    subprocess.Popen(
                        [sys.executable, *args], env=env, stdout=log, stderr=log, creationflags=flags
                    )
                )
            health = wait_for("http://127.0.0.1:18000/health").json()
            ui_health = wait_for("http://127.0.0.1:18501/_stcore/health").text
            homepage = wait_for("http://127.0.0.1:18501/")
            response = httpx.post(
                "http://127.0.0.1:18000/analyze",
                json={"question": "삼성전자와 SK하이닉스의 2023~2025년 매출 비교"},
                timeout=30,
            )
            response.raise_for_status()
            result = response.json()
            assert len(result["financials"]) == 6 and result["mode"] == "mock"
            # Execute the real UI script against the running FastAPI service.
            os.environ["FINSIGHT_API_URL"] = env["FINSIGHT_API_URL"]
            from streamlit.testing.v1 import AppTest

            app = AppTest.from_file(str(Path("ui/app.py").resolve())).run(timeout=30)
            app.button[0].click().run(timeout=30)
            assert not app.exception and len(app.dataframe[0].value) == 6
            report = {
                "api_health": health,
                "streamlit_health": ui_health,
                "homepage_status": homepage.status_code,
                "analyze_status": response.status_code,
                "financial_rows": 6,
                "ui_script_against_real_server": "passed",
                "browser_visual_inspection": "not performed",
                "mode": "mock",
            }
            Path("evaluation/smoke-results.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
            print(json.dumps(report, indent=2))
    finally:
        for process in processes:
            process.terminate()
        for process in processes:
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()


if __name__ == "__main__":
    main()
