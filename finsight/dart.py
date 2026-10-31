import io
import re
import threading
import time
import zipfile
from collections import deque
from datetime import date

import httpx
from defusedxml import ElementTree

from finsight.config import Settings
from finsight.finance import DataError, normalize
from finsight.models import COMPANIES


class RateLimit(DataError):
    pass


class Limiter:
    def __init__(self, limit: int):
        self.limit = limit
        self.calls: deque[float] = deque()
        self.lock = threading.Lock()

    def acquire(self):
        with self.lock:
            now = time.monotonic()
            while self.calls and self.calls[0] <= now - 60:
                self.calls.popleft()
            if len(self.calls) >= self.limit:
                raise RateLimit("분당 요청 한도에 도달했습니다. 잠시 후 다시 시도하세요.")
            self.calls.append(now)


def unzip_xml(content: bytes) -> list[bytes]:
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            files = [f for f in archive.infolist() if f.filename.lower().endswith(".xml")]
            if not files or len(files) > 100 or sum(f.file_size for f in files) > 80_000_000:
                raise DataError("공시 압축 파일의 크기 또는 구성이 허용 범위를 벗어났습니다.")
            # Read in memory; never extract untrusted file paths.
            return [archive.read(f) for f in files]
    except zipfile.BadZipFile as exc:
        raise DataError("공시 원문 다운로드가 실패했습니다. 인증/제공 여부를 확인하세요.") from exc


class DartClient:
    def __init__(self, config: Settings, client: httpx.Client | None = None):
        config.require_live()
        self.config = config
        self.client = client or httpx.Client(timeout=config.request_timeout, follow_redirects=False)
        self.limiter = Limiter(config.dart_calls_per_minute)
        self.codes: dict[str, str] = {}

    def get(self, endpoint: str, params: dict) -> bytes:
        for attempt in range(3):
            self.limiter.acquire()
            try:
                # Limit downloaded bytes before buffering the response. Do not expose exception URLs (key).
                with self.client.stream(
                    "GET",
                    f"https://opendart.fss.or.kr/api/{endpoint}",
                    params={"crtfc_key": self.config.dart_api_key.get_secret_value(), **params},
                ) as response:
                    if (response.status_code == 429 or response.status_code >= 500) and attempt < 2:
                        time.sleep(0.25 * 2**attempt)
                        continue
                    response.raise_for_status()
                    chunks, size = [], 0
                    for chunk in response.iter_bytes():
                        size += len(chunk)
                        if size > 30_000_000:
                            raise DataError("API 응답 크기가 허용 범위를 초과했습니다.")
                        chunks.append(chunk)
                    return b"".join(chunks)
            except (httpx.TimeoutException, httpx.NetworkError):
                if attempt < 2:
                    time.sleep(0.25 * 2**attempt)
                    continue
            except httpx.HTTPStatusError:
                pass
            raise DataError("OpenDART 연결 오류입니다. 인증키·네트워크·API 상태를 확인하세요.")
        raise DataError("OpenDART 재시도 한도를 초과했습니다.")

    def json(self, endpoint: str, params: dict) -> list[dict]:
        import json

        try:
            payload = json.loads(self.get(endpoint, params))
            status = payload.get("status")
        except (ValueError, AttributeError) as exc:
            raise DataError("OpenDART 응답 형식이 올바르지 않습니다.") from exc
        if status == "013":
            return []
        if status != "000":
            errors = {
                "010": "등록되지 않은 인증키",
                "011": "사용할 수 없는 인증키",
                "020": "API 요청 한도 초과",
                "100": "요청 필드 오류",
                "800": "점검 중",
            }
            raise DataError(f"OpenDART: {errors.get(status, 'API 처리 오류')}")
        rows = payload.get("list", [])
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise DataError("OpenDART 목록 형식 오류")
        return rows

    def corp_code(self, company: str) -> str:
        if company not in COMPANIES:
            raise DataError("지원하지 않는 기업입니다.")
        if not self.codes:
            xml = unzip_xml(self.get("corpCode.xml", {}))[0]
            try:
                root = ElementTree.fromstring(xml)
                for row in root.findall("list"):
                    stock = row.findtext("stock_code", "").strip()
                    for name, code in COMPANIES.items():
                        if stock == code:
                            corp = row.findtext("corp_code", "")
                            if re.fullmatch(r"\d{8}", corp):
                                self.codes[name] = corp
            except Exception as exc:
                raise DataError("기업 고유번호 XML을 읽을 수 없습니다.") from exc
        if company not in self.codes:
            raise DataError("기업 고유번호를 찾지 못했습니다.")
        return self.codes[company]

    def financial(self, company: str, year: int, basis: str):
        rows = self.json(
            "fnlttSinglAcntAll.json",
            {
                "corp_code": self.corp_code(company),
                "bsns_year": str(year),
                "reprt_code": "11011",
                "fs_div": basis,
            },
        )
        if not rows:
            raise DataError(f"{company} {year} {basis} 연간 재무정보가 없습니다.")
        return normalize(rows, company, year, basis)

    def annual_disclosure(self, company: str, year: int) -> dict:
        # Include subsequent corrections; filter by report title fiscal year, never filing year alone.
        matches = []
        for page in range(1, 11):
            rows = self.json(
                "list.json",
                {
                    "corp_code": self.corp_code(company),
                    "bgn_de": f"{year + 1}0101",
                    "end_de": date.today().strftime("%Y%m%d"),
                    "pblntf_ty": "A",
                    "last_reprt_at": "Y",
                    "page_count": "100",
                    "page_no": str(page),
                    "sort": "date",
                    "sort_mth": "desc",
                },
            )
            matches.extend(
                r for r in rows if re.search(rf"사업보고서\s*\({year}\.12\)", r.get("report_nm", ""))
            )
            if len(rows) < 100:
                break
        else:
            raise DataError("공시 목록이 조회 범위를 초과했습니다.")
        if not matches:
            raise DataError(f"{company} {year} 사업보고서를 찾지 못했습니다.")
        return max(matches, key=lambda r: r["rcept_no"])

    def document(self, receipt: str) -> list[bytes]:
        if not re.fullmatch(r"\d{14}", receipt):
            raise DataError("접수번호 형식 오류")
        return unzip_xml(self.get("document.xml", {"rcept_no": receipt}))
