# Google Takeout 적재(staging) 파이프라인 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Google Takeout으로 받은 사진 중 `taken_at ∈ [2011-01-01, C)` 구간만 골라(C=맥 보관함 시작일), Takeout 내부 중복을 제거하고 `data/google_photos/staged/` + `manifest.jsonl`로 적재하는 검증된 스크립트를 만든다.

**Architecture:** 순수 함수 단위로 분해한 파이프라인 — sidecar 파싱 → media walk + record 빌드 + 날짜 필터 → BLAKE3 내부 dedup → staging + manifest. 실제 Takeout 데이터는 사용자가 수동 익스포트해야 하므로(구글 처리 지연), **모든 로직은 합성 fixture로 TDD**하고 실데이터 실행은 마지막 게이트 태스크로 분리한다. 상한 C는 osxphotos로 맥 보관함 연도 분포를 뽑아 **사용자가 확정**한다(자동 휴리스틱 미사용).

**Tech Stack:** Python 3.12, uv, pytest, osxphotos(C 측정), blake3(dedup), Pillow+pillow-heif(EXIF 폴백). 근거: [ADR-0005](../../adr/0005-google-takeout-source.md).

---

## File Structure

| 파일 | 책임 |
|---|---|
| `pyproject.toml` (modify) | deps 선언(osxphotos·blake3·pillow·pillow-heif) + pytest `pythonpath=["src"]` |
| `src/eddr/__init__.py` (create) | 패키지 루트 (빈 파일) |
| `src/eddr/photos_library/__init__.py` (create) | 빈 파일 |
| `src/eddr/photos_library/coverage.py` (create) | osxphotos로 촬영일 수집(I/O) + 연도 집계(순수) → C 결정 근거 |
| `src/eddr/google_takeout/__init__.py` (create) | 빈 파일 |
| `src/eddr/google_takeout/sidecar.py` (create) | JSON 사이드카 탐색(절단 내성) + 메타 파싱 |
| `src/eddr/google_takeout/walk.py` (create) | media 폴더 walk + record 빌드(EXIF 폴백) + 날짜 필터 |
| `src/eddr/google_takeout/stage.py` (create) | BLAKE3 내부 dedup + staged/ 복사 + manifest.jsonl |
| `src/eddr/google_takeout/ingest.py` (create) | 오케스트레이터 + `python -m eddr.google_takeout.ingest` CLI |
| `tests/conftest.py` (create) | 합성 Takeout 트리 fixture(PIL 생성 이미지 + 사이드카) |
| `tests/photos_library/test_coverage.py` (create) | 연도 집계 순수함수 테스트 |
| `tests/google_takeout/test_sidecar.py` (create) | 사이드카 탐색/파싱 테스트(절단 케이스 포함) |
| `tests/google_takeout/test_walk.py` (create) | record 빌드 + 날짜 필터 테스트 |
| `tests/google_takeout/test_stage.py` (create) | dedup + manifest 테스트 |
| `tests/google_takeout/test_ingest.py` (create) | 전체 fixture 통합 테스트 |

**데이터 레이아웃** (모두 gitignore된 `data/` 하위):
```
data/google_photos/raw/        # 사용자가 Takeout zip을 여기에 둔다 (수동)
data/google_photos/extracted/  # 압축 해제 작업 트리
data/google_photos/staged/     # 필터·dedup 후 보관 (파일명 = <blake3>.<ext>)
data/google_photos/manifest.jsonl  # 보관된 record 1줄당 1건
```

**manifest record 스키마** (메인 `photos` 테이블 컬럼명과 정렬 → 후속 통합 용이):
```json
{"source":"google_takeout","source_uri":"Photos from 2015/IMG_1234.jpg",
 "staged_path":"data/google_photos/staged/af3b...c1.jpg","content_hash":"af3b...c1",
 "taken_at":"2015-08-15T05:21:18+00:00","latitude":37.5,"longitude":127.0,
 "description":"","people":[],"google_media_key":null,"original_filename":"IMG_1234.jpg"}
```

---

## Task 1: 프로젝트 스켈레톤 + 의존성 선언

**Files:**
- Modify: `pyproject.toml`
- Create: `src/eddr/__init__.py`, `src/eddr/photos_library/__init__.py`, `src/eddr/google_takeout/__init__.py`
- Create: `tests/__init__.py`, `tests/photos_library/__init__.py`, `tests/google_takeout/__init__.py`

- [ ] **Step 1: data/ 가 gitignore되는지 확인 (프라이버시 안전장치)**

Run: `git -C /Users/shingh/works/eddr check-ignore data/google_photos/staged/x.jpg; grep -n "data" /Users/shingh/works/eddr/.gitignore 2>/dev/null`
Expected: `check-ignore`가 경로를 출력(=무시됨)하거나 `.gitignore`에 `data/` 패턴 존재. 만약 무시되지 **않으면** `.gitignore`에 `data/` 한 줄을 추가하고 멈춰 사용자에게 보고.

- [ ] **Step 2: 패키지/테스트 디렉터리와 빈 `__init__.py` 생성**

Run:
```bash
mkdir -p /Users/shingh/works/eddr/src/eddr/photos_library \
         /Users/shingh/works/eddr/src/eddr/google_takeout \
         /Users/shingh/works/eddr/tests/photos_library \
         /Users/shingh/works/eddr/tests/google_takeout
touch /Users/shingh/works/eddr/src/eddr/__init__.py \
      /Users/shingh/works/eddr/src/eddr/photos_library/__init__.py \
      /Users/shingh/works/eddr/src/eddr/google_takeout/__init__.py \
      /Users/shingh/works/eddr/tests/__init__.py \
      /Users/shingh/works/eddr/tests/photos_library/__init__.py \
      /Users/shingh/works/eddr/tests/google_takeout/__init__.py
```

- [ ] **Step 3: deps 선언 + pytest 설정**

`uv add`로 런타임 deps와 pytest(dev)를 추가:
```bash
cd /Users/shingh/works/eddr && uv add osxphotos blake3 pillow pillow-heif && uv add --dev pytest
```
그다음 `pyproject.toml` 끝에 pytest 설정 블록을 추가(빌드 백엔드 없이 src 레이아웃을 import 가능하게):
```toml
[tool.pytest.ini_options]
pythonpath = ["src"]
testpaths = ["tests"]
```

- [ ] **Step 4: import 경로 점검용 smoke 테스트**

Create `tests/test_smoke.py`:
```python
def test_packages_importable():
    import eddr.google_takeout  # noqa: F401
    import eddr.photos_library  # noqa: F401
```

- [ ] **Step 5: 실행해서 통과 확인**

Run: `cd /Users/shingh/works/eddr && uv run pytest tests/test_smoke.py -v`
Expected: PASS (`eddr` 패키지가 `src/`에서 import됨)

- [ ] **Step 6: Commit**

```bash
git -C /Users/shingh/works/eddr add pyproject.toml uv.lock src tests
git -C /Users/shingh/works/eddr commit -m "feat: 프로젝트 스켈레톤 + Takeout 적재용 deps 선언

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: 맥 보관함 연도 분포 측정 (상한 C 결정 근거)

osxphotos I/O는 단위테스트하기 어렵고 Photos 접근 권한이 필요하므로, **순수 집계 함수**(`summarize_years`)와 **I/O 함수**(`query_taken_dates`)를 분리한다. 집계만 TDD하고, I/O는 실행으로 검증한다.

**Files:**
- Create: `src/eddr/photos_library/coverage.py`
- Test: `tests/photos_library/test_coverage.py`

- [ ] **Step 1: 집계 순수함수의 실패 테스트 작성**

Create `tests/photos_library/test_coverage.py`:
```python
from datetime import datetime
from eddr.photos_library.coverage import summarize_years


def test_summarize_years_counts_per_year():
    dates = [
        datetime(2015, 1, 1), datetime(2015, 6, 1),
        datetime(2021, 3, 1), datetime(2021, 4, 1), datetime(2021, 5, 1),
    ]
    assert summarize_years(dates) == {2015: 2, 2021: 3}


def test_summarize_years_empty():
    assert summarize_years([]) == {}
```

- [ ] **Step 2: 실행해서 실패 확인**

Run: `cd /Users/shingh/works/eddr && uv run pytest tests/photos_library/test_coverage.py -v`
Expected: FAIL (`ImportError` / `summarize_years` 없음)

- [ ] **Step 3: 최소 구현**

Create `src/eddr/photos_library/coverage.py`:
```python
"""맥 Photos Library의 촬영일 분포를 측정해 상한 C 결정을 돕는다 (ADR-0005)."""
from __future__ import annotations

from collections import Counter
from datetime import datetime


def summarize_years(dates: list[datetime]) -> dict[int, int]:
    """촬영일 리스트 → {연도: 장수}."""
    return dict(sorted(Counter(d.year for d in dates).items()))


def query_taken_dates() -> list[datetime]:
    """Photos Library에서 이미지(동영상 제외)의 촬영일을 읽는다.

    Photos 접근 권한 필요. 권한이 없으면 osxphotos가 빈 결과/예외를 낼 수 있다.
    """
    import osxphotos

    db = osxphotos.PhotosDB()
    return [p.date for p in db.photos(movies=False) if p.date is not None]


def print_year_table(year_counts: dict[int, int]) -> None:
    total = sum(year_counts.values())
    print(f"{'YEAR':>6} {'COUNT':>7} {'CUM%':>6}")
    cum = 0
    for year, n in year_counts.items():
        cum += n
        print(f"{year:>6} {n:>7} {100 * cum / total:>5.1f}%")
    print(f"{'TOTAL':>6} {total:>7}")


if __name__ == "__main__":
    print_year_table(summarize_years(query_taken_dates()))
```

- [ ] **Step 4: 집계 테스트 통과 확인**

Run: `cd /Users/shingh/works/eddr && uv run pytest tests/photos_library/test_coverage.py -v`
Expected: PASS

- [ ] **Step 5: 실데이터로 연도 분포 실행 (Photos 권한 검증 겸용)**

Run: `cd /Users/shingh/works/eddr && uv run python -m eddr.photos_library.coverage`
Expected: 연도별 장수 + 누적% 테이블 출력. 총합이 EDA 실측(이미지 8,701) 근방이면 권한·경로 정상.
- **권한 오류 시**(빈 결과/Operation not permitted): 멈추고 사용자에게 *System Settings → Privacy & Security → Full Disk Access*에 터미널 추가를 요청한다.

- [ ] **Step 6: 사용자에게 C 확정 요청**

출력 테이블을 사용자에게 보여주고 **조밀 커버리지 시작일 C**를 확정받는다(예: "2021년부터 매년 1천 장+ → C=2021-01-01"). 자동 결정하지 않는다. 확정된 C를 Task 4·6의 `--coverage-start`로 쓴다.

- [ ] **Step 7: Commit**

```bash
git -C /Users/shingh/works/eddr add src/eddr/photos_library tests/photos_library
git -C /Users/shingh/works/eddr commit -m "feat: 맥 보관함 연도 분포 측정(coverage) — 상한 C 근거

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: JSON 사이드카 탐색 + 파싱

Takeout 메타는 사이드카가 권위 소스. 파일명은 신형 `*.supplemental-metadata.json`, 구형 `*.json`, **46자 절단**(`*.supplemental-metad.json`), `-edited` 변형이 섞인다.

**Files:**
- Create: `src/eddr/google_takeout/sidecar.py`
- Test: `tests/google_takeout/test_sidecar.py`

- [ ] **Step 1: 실패 테스트 작성**

Create `tests/google_takeout/test_sidecar.py`:
```python
import json
from datetime import timezone
from pathlib import Path

from eddr.google_takeout.sidecar import find_sidecar, parse_sidecar


def _write(p: Path, payload: dict) -> None:
    p.write_text(json.dumps(payload), encoding="utf-8")


def test_find_exact_supplemental(tmp_path: Path):
    (tmp_path / "IMG_1.jpg").touch()
    sc = tmp_path / "IMG_1.jpg.supplemental-metadata.json"
    _write(sc, {})
    assert find_sidecar(tmp_path / "IMG_1.jpg") == sc


def test_find_truncated_sidecar(tmp_path: Path):
    media = tmp_path / "IMG_20230815_142536.jpg"
    media.touch()
    # 신형 접미사가 46자 한도로 절단된 케이스
    sc = tmp_path / "IMG_20230815_142536.jpg.supplemental-metad.json"
    _write(sc, {})
    assert find_sidecar(media) == sc


def test_find_edited_falls_back_to_base(tmp_path: Path):
    (tmp_path / "IMG_2-edited.jpg").touch()
    sc = tmp_path / "IMG_2.jpg.supplemental-metadata.json"
    _write(sc, {})
    assert find_sidecar(tmp_path / "IMG_2-edited.jpg") == sc


def test_parse_sidecar_fields(tmp_path: Path):
    sc = tmp_path / "x.json"
    _write(sc, {
        "title": "x.jpg", "description": "바다",
        "photoTakenTime": {"timestamp": "1439616078"},
        "geoData": {"latitude": 37.5, "longitude": 127.0},
        "people": [{"name": "철수"}],
    })
    meta = parse_sidecar(sc)
    assert meta.taken_at.tzinfo == timezone.utc
    assert meta.taken_at.year == 2015
    assert (meta.latitude, meta.longitude) == (37.5, 127.0)
    assert meta.description == "바다"
    assert meta.people == ["철수"]


def test_parse_sidecar_zero_geo_is_none(tmp_path: Path):
    sc = tmp_path / "y.json"
    _write(sc, {"photoTakenTime": {"timestamp": "1439616078"},
                "geoData": {"latitude": 0.0, "longitude": 0.0}})
    meta = parse_sidecar(sc)
    assert meta.latitude is None and meta.longitude is None
```

- [ ] **Step 2: 실행해서 실패 확인**

Run: `cd /Users/shingh/works/eddr && uv run pytest tests/google_takeout/test_sidecar.py -v`
Expected: FAIL (`ImportError`)

- [ ] **Step 3: 최소 구현**

Create `src/eddr/google_takeout/sidecar.py`:
```python
"""Takeout JSON 사이드카 탐색(절단 내성) + 파싱 (ADR-0005)."""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass
class SidecarMeta:
    taken_at: datetime | None
    latitude: float | None
    longitude: float | None
    description: str
    people: list[str]
    google_media_key: str | None


_SUFFIXES = (".supplemental-metadata.json", ".json")


def _media_prefix(json_name: str) -> str:
    """사이드카 파일명에서 media 파일명 부분을 복원(절단 포함)."""
    stem = json_name
    for marker in _SUFFIXES:
        if stem.endswith(marker):
            stem = stem[: -len(marker)]
            break
    # ".supplemental..."가 절단된 잔여물 제거
    if ".supplemental" in stem:
        stem = stem[: stem.index(".supplemental")]
    return stem


def find_sidecar(media_path: Path) -> Path | None:
    d, name = media_path.parent, media_path.name
    # 1) 정확 일치
    for suffix in _SUFFIXES:
        cand = d / (name + suffix)
        if cand.exists():
            return cand
    # 2) -edited → 원본 사이드카
    if "-edited" in name:
        base = name.replace("-edited", "")
        for suffix in _SUFFIXES:
            cand = d / (base + suffix)
            if cand.exists():
                return cand
        name = base
    # 3) 절단 내성: media_prefix가 name의 접두사인 것 중 최장
    best, best_len = None, 0
    for j in d.glob("*.json"):
        prefix = _media_prefix(j.name)
        if prefix and name.startswith(prefix) and len(prefix) > best_len:
            best, best_len = j, len(prefix)
    return best


def parse_sidecar(path: Path) -> SidecarMeta:
    data = json.loads(path.read_text(encoding="utf-8"))
    ts = data.get("photoTakenTime", {}).get("timestamp")
    taken_at = (
        datetime.fromtimestamp(int(ts), tz=timezone.utc) if ts else None
    )
    lat = lon = None
    for key in ("geoData", "geoDataExif"):
        geo = data.get(key) or {}
        if geo.get("latitude") or geo.get("longitude"):  # 0.0/0.0 → 무시
            lat, lon = geo.get("latitude"), geo.get("longitude")
            break
    people = [p["name"] for p in data.get("people", []) if p.get("name")]
    return SidecarMeta(
        taken_at=taken_at, latitude=lat, longitude=lon,
        description=data.get("description", "") or "",
        people=people,
        google_media_key=(data.get("googlePhotosOrigin") or {}).get("mobileUpload", {}).get("deviceType"),
    )
```

- [ ] **Step 4: 통과 확인**

Run: `cd /Users/shingh/works/eddr && uv run pytest tests/google_takeout/test_sidecar.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git -C /Users/shingh/works/eddr add src/eddr/google_takeout/sidecar.py tests/google_takeout/test_sidecar.py
git -C /Users/shingh/works/eddr commit -m "feat: Takeout 사이드카 탐색(절단 내성)+파싱

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 4: media walk + record 빌드 + 날짜 필터

폴더를 walk하며 미디어 파일마다 record를 만든다. 사이드카가 권위, 없으면 EXIF 폴백. 그다음 `[start, C)` 날짜 필터.

**Files:**
- Create: `src/eddr/google_takeout/walk.py`
- Test: `tests/google_takeout/test_walk.py`

- [ ] **Step 1: 실패 테스트 작성**

Create `tests/google_takeout/test_walk.py`:
```python
import json
from datetime import date
from pathlib import Path

from eddr.google_takeout.walk import build_records, in_date_range


def _img(p: Path) -> None:
    from PIL import Image
    Image.new("RGB", (4, 4), (10, 20, 30)).save(p)


def _sc(p: Path, ts: str) -> None:
    p.write_text(json.dumps({"photoTakenTime": {"timestamp": ts}}), encoding="utf-8")


def test_in_date_range():
    lo, hi = date(2011, 1, 1), date(2021, 1, 1)
    assert in_date_range(date(2015, 6, 1), lo, hi)
    assert in_date_range(date(2011, 1, 1), lo, hi)        # 하한 포함
    assert not in_date_range(date(2021, 1, 1), lo, hi)    # 상한 제외
    assert not in_date_range(date(2010, 12, 31), lo, hi)


def test_build_records_uses_sidecar(tmp_path: Path):
    media = tmp_path / "IMG_9.jpg"
    _img(media)
    _sc(tmp_path / "IMG_9.jpg.supplemental-metadata.json", "1439616078")  # 2015
    records = build_records(tmp_path)
    assert len(records) == 1
    assert records[0].taken_at.year == 2015
    assert records[0].source_uri.endswith("IMG_9.jpg")


def test_build_records_skips_json_and_nonmedia(tmp_path: Path):
    _img(tmp_path / "a.jpg")
    _sc(tmp_path / "a.jpg.supplemental-metadata.json", "1439616078")
    (tmp_path / "metadata.json").write_text("{}", encoding="utf-8")
    (tmp_path / "notes.txt").write_text("x", encoding="utf-8")
    records = build_records(tmp_path)
    assert len(records) == 1  # a.jpg만
```

- [ ] **Step 2: 실행해서 실패 확인**

Run: `cd /Users/shingh/works/eddr && uv run pytest tests/google_takeout/test_walk.py -v`
Expected: FAIL (`ImportError`)

- [ ] **Step 3: 최소 구현**

Create `src/eddr/google_takeout/walk.py`:
```python
"""Takeout 폴더 walk → record 빌드 → 날짜 필터 (ADR-0005)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

from eddr.google_takeout.sidecar import find_sidecar, parse_sidecar

_MEDIA_EXT = {".jpg", ".jpeg", ".png", ".heic", ".heif", ".gif", ".webp"}


@dataclass
class MediaRecord:
    path: Path
    source_uri: str
    taken_at: datetime | None
    latitude: float | None
    longitude: float | None
    description: str
    people: list[str]
    google_media_key: str | None
    original_filename: str


def in_date_range(d: date, lo: date, hi: date) -> bool:
    """[lo, hi) 반열린 구간."""
    return lo <= d < hi


def _exif_taken_at(path: Path) -> datetime | None:
    try:
        import pillow_heif
        pillow_heif.register_heif_opener()
        from PIL import Image
        exif = Image.open(path).getexif()
        raw = exif.get(36867) or exif.get(306)  # DateTimeOriginal / DateTime
        if raw:
            return datetime.strptime(raw, "%Y:%m:%d %H:%M:%S").replace(tzinfo=timezone.utc)
    except Exception:
        return None
    return None


def build_records(root: Path) -> list[MediaRecord]:
    records: list[MediaRecord] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in _MEDIA_EXT:
            continue
        sidecar = find_sidecar(path)
        meta = parse_sidecar(sidecar) if sidecar else None
        taken_at = (meta.taken_at if meta and meta.taken_at else _exif_taken_at(path))
        records.append(MediaRecord(
            path=path,
            source_uri=str(path.relative_to(root)),
            taken_at=taken_at,
            latitude=meta.latitude if meta else None,
            longitude=meta.longitude if meta else None,
            description=meta.description if meta else "",
            people=meta.people if meta else [],
            google_media_key=meta.google_media_key if meta else None,
            original_filename=path.name,
        ))
    return records


def filter_by_date(records: list[MediaRecord], lo: date, hi: date) -> list[MediaRecord]:
    return [r for r in records if r.taken_at and in_date_range(r.taken_at.date(), lo, hi)]
```

- [ ] **Step 4: 통과 확인**

Run: `cd /Users/shingh/works/eddr && uv run pytest tests/google_takeout/test_walk.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git -C /Users/shingh/works/eddr add src/eddr/google_takeout/walk.py tests/google_takeout/test_walk.py
git -C /Users/shingh/works/eddr commit -m "feat: Takeout media walk + record 빌드 + 날짜 필터

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 5: BLAKE3 내부 dedup + staging + manifest

연도폴더↔앨범폴더 동일 파일(바이트 동일)을 BLAKE3로 1장만 남기고, `staged/<hash>.<ext>`로 복사 후 `manifest.jsonl` 기록.

**Files:**
- Create: `src/eddr/google_takeout/stage.py`
- Test: `tests/google_takeout/test_stage.py`

- [ ] **Step 1: 실패 테스트 작성**

Create `tests/google_takeout/test_stage.py`:
```python
import json
from datetime import datetime, timezone
from pathlib import Path

from eddr.google_takeout.stage import blake3_hex, dedup_by_content, stage_records
from eddr.google_takeout.walk import MediaRecord


def _rec(path: Path, uri: str) -> MediaRecord:
    return MediaRecord(path=path, source_uri=uri,
                       taken_at=datetime(2015, 6, 1, tzinfo=timezone.utc),
                       latitude=None, longitude=None, description="",
                       people=[], google_media_key=None, original_filename=path.name)


def test_blake3_hex_stable(tmp_path: Path):
    f = tmp_path / "a.bin"
    f.write_bytes(b"hello")
    assert blake3_hex(f) == blake3_hex(f)
    assert len(blake3_hex(f)) == 64


def test_dedup_keeps_one_per_content(tmp_path: Path):
    (tmp_path / "yr").mkdir(); (tmp_path / "al").mkdir()
    a = tmp_path / "yr" / "IMG.jpg"; a.write_bytes(b"SAME")
    b = tmp_path / "al" / "IMG.jpg"; b.write_bytes(b"SAME")  # 동일 바이트
    c = tmp_path / "yr" / "OTHER.jpg"; c.write_bytes(b"DIFF")
    kept = dedup_by_content([_rec(a, "yr/IMG.jpg"), _rec(b, "al/IMG.jpg"), _rec(c, "yr/OTHER.jpg")])
    assert len(kept) == 2
    assert kept[0].source_uri == "yr/IMG.jpg"  # 정렬상 먼저(연도폴더) 우선


def test_stage_writes_files_and_manifest(tmp_path: Path):
    src = tmp_path / "IMG.jpg"; src.write_bytes(b"DATA")
    out = tmp_path / "out"
    stage_records([_rec(src, "yr/IMG.jpg")], out)
    staged = list((out / "staged").glob("*.jpg"))
    assert len(staged) == 1
    manifest = (out / "manifest.jsonl").read_text(encoding="utf-8").strip().splitlines()
    row = json.loads(manifest[0])
    assert row["source"] == "google_takeout"
    assert row["content_hash"] == staged[0].stem
    assert row["taken_at"].startswith("2015-06-01")
```

- [ ] **Step 2: 실행해서 실패 확인**

Run: `cd /Users/shingh/works/eddr && uv run pytest tests/google_takeout/test_stage.py -v`
Expected: FAIL (`ImportError`)

- [ ] **Step 3: 최소 구현**

Create `src/eddr/google_takeout/stage.py`:
```python
"""BLAKE3 내부 dedup + staged/ 복사 + manifest.jsonl (ADR-0005)."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from blake3 import blake3

from eddr.google_takeout.walk import MediaRecord


def blake3_hex(path: Path) -> str:
    h = blake3()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def dedup_by_content(records: list[MediaRecord]) -> list[MediaRecord]:
    """content_hash별 1장. source_uri 정렬 순서로 먼저 오는 것을 보관."""
    seen: dict[str, MediaRecord] = {}
    for r in sorted(records, key=lambda r: r.source_uri):
        key = blake3_hex(r.path)
        seen.setdefault(key, r)
    return list(seen.values())


def stage_records(records: list[MediaRecord], out_dir: Path) -> int:
    staged_dir = out_dir / "staged"
    staged_dir.mkdir(parents=True, exist_ok=True)
    manifest = out_dir / "manifest.jsonl"
    written = 0
    with manifest.open("w", encoding="utf-8") as mf:
        for r in records:
            h = blake3_hex(r.path)
            dest = staged_dir / f"{h}{r.path.suffix.lower()}"
            if not dest.exists():
                shutil.copy2(r.path, dest)
            mf.write(json.dumps({
                "source": "google_takeout",
                "source_uri": r.source_uri,
                "staged_path": str(dest),
                "content_hash": h,
                "taken_at": r.taken_at.isoformat() if r.taken_at else None,
                "latitude": r.latitude, "longitude": r.longitude,
                "description": r.description, "people": r.people,
                "google_media_key": r.google_media_key,
                "original_filename": r.original_filename,
            }, ensure_ascii=False) + "\n")
            written += 1
    return written
```

- [ ] **Step 4: 통과 확인**

Run: `cd /Users/shingh/works/eddr && uv run pytest tests/google_takeout/test_stage.py -v`
Expected: PASS (3 tests). `dedup_by_content`이 같은 파일을 두 번 해싱하므로, 대용량에선 Task 6에서 해시 캐시로 합친다.

- [ ] **Step 5: Commit**

```bash
git -C /Users/shingh/works/eddr add src/eddr/google_takeout/stage.py tests/google_takeout/test_stage.py
git -C /Users/shingh/works/eddr commit -m "feat: Takeout 내부 BLAKE3 dedup + staging + manifest

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 6: 오케스트레이터 + CLI + 전체 fixture 통합 테스트

`raw/`의 zip 압축 해제 → walk → 날짜 필터 → dedup → stage를 잇고, 합성 Takeout 트리로 end-to-end 검증.

**Files:**
- Create: `src/eddr/google_takeout/ingest.py`
- Create: `tests/conftest.py` (합성 Takeout fixture)
- Test: `tests/google_takeout/test_ingest.py`

- [ ] **Step 1: 합성 fixture 작성 (conftest)**

Create `tests/conftest.py`:
```python
"""합성 Takeout 트리: 정상/중복/범위밖/절단 사이드카/-edited를 한 번에 재현."""
import json
from pathlib import Path

import pytest
from PIL import Image


def _img(p: Path, color: tuple[int, int, int]) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (8, 8), color).save(p)


def _sc(p: Path, ts: str, **extra) -> None:
    payload = {"photoTakenTime": {"timestamp": ts}, **extra}
    p.write_text(json.dumps(payload), encoding="utf-8")


# 타임스탬프: 2015-08-15(in), 2009-01-01(범위밖 과거), 2023-08-15(범위밖 미래=overlap)
TS_2015, TS_2009, TS_2023 = "1439616078", "1230768000", "1692072078"


@pytest.fixture
def takeout_tree(tmp_path: Path) -> Path:
    root = tmp_path / "Takeout" / "Google Photos"
    # 1) 정상 2015 사진 (연도폴더)
    _img(root / "Photos from 2015" / "IMG_A.jpg", (1, 2, 3))
    _sc(root / "Photos from 2015" / "IMG_A.jpg.supplemental-metadata.json", TS_2015,
        geoData={"latitude": 37.5, "longitude": 127.0}, description="제주")
    # 2) 같은 사진이 앨범폴더에도 중복 (바이트 동일) → dedup 대상
    _img(root / "여행앨범" / "IMG_A.jpg", (1, 2, 3))
    _sc(root / "여행앨범" / "IMG_A.jpg.supplemental-metadata.json", TS_2015)
    # 3) 절단된 사이드카를 가진 2015 사진
    _img(root / "Photos from 2015" / "IMG_LONGNAME_0001.jpg", (4, 5, 6))
    _sc(root / "Photos from 2015" / "IMG_LONGNAME_0001.jpg.supplemental-metad.json", TS_2015)
    # 4) 범위 밖(2009) — 하한 미만
    _img(root / "Photos from 2009" / "OLD.jpg", (7, 8, 9))
    _sc(root / "Photos from 2009" / "OLD.jpg.supplemental-metadata.json", TS_2009)
    # 5) 범위 밖(2023) — 상한 이상(overlap 구간)
    _img(root / "Photos from 2023" / "NEW.jpg", (9, 9, 9))
    _sc(root / "Photos from 2023" / "NEW.jpg.supplemental-metadata.json", TS_2023)
    return tmp_path
```

- [ ] **Step 2: 통합 실패 테스트 작성**

Create `tests/google_takeout/test_ingest.py`:
```python
import json
from datetime import date
from pathlib import Path

from eddr.google_takeout.ingest import ingest


def test_ingest_end_to_end(takeout_tree: Path):
    out = takeout_tree / "out"
    # C = 2021-01-01, 하한 2011-01-01 → 2015 사진만 보관, 중복 1장 제거
    n = ingest(extracted_root=takeout_tree, out_dir=out,
               start=date(2011, 1, 1), coverage_start=date(2021, 1, 1))
    rows = [json.loads(l) for l in (out / "manifest.jsonl").read_text("utf-8").splitlines()]
    uris = {r["source_uri"].split("/")[-1] for r in rows}
    # IMG_A(중복 제거 후 1장) + IMG_LONGNAME_0001 = 2장
    assert n == 2
    assert "OLD.jpg" not in uris       # 2009 하한 미만 제외
    assert "NEW.jpg" not in uris       # 2023 상한 이상 제외(overlap 회피)
    staged = list((out / "staged").glob("*.jpg"))
    assert len(staged) == 2            # 중복 IMG_A는 1개 파일
    assert all(r["latitude"] in (37.5, None) for r in rows)
```

- [ ] **Step 3: 실행해서 실패 확인**

Run: `cd /Users/shingh/works/eddr && uv run pytest tests/google_takeout/test_ingest.py -v`
Expected: FAIL (`ImportError`)

- [ ] **Step 4: 오케스트레이터 + CLI 구현**

Create `src/eddr/google_takeout/ingest.py`:
```python
"""Takeout 적재 오케스트레이터 + CLI (ADR-0005).

사용 흐름(수동 획득):
  1) Takeout에서 구글 포토 [2011..year(C)] 연도앨범 선택 → 다운로드
  2) zip을 data/google_photos/raw/ 에 둔다
  3) python -m eddr.google_takeout.ingest --coverage-start YYYY-MM-DD
"""
from __future__ import annotations

import argparse
import zipfile
from datetime import date, datetime
from pathlib import Path

from eddr.google_takeout.stage import dedup_by_content, stage_records
from eddr.google_takeout.walk import build_records, filter_by_date

_DEFAULT_ROOT = Path("data/google_photos")


def extract_raw(raw_dir: Path, extracted_dir: Path) -> None:
    """raw/의 모든 zip을 extracted/로 푼다(이미 푼 건 건너뜀)."""
    extracted_dir.mkdir(parents=True, exist_ok=True)
    for zp in sorted(raw_dir.glob("*.zip")):
        with zipfile.ZipFile(zp) as z:
            z.extractall(extracted_dir)


def ingest(extracted_root: Path, out_dir: Path, start: date, coverage_start: date) -> int:
    records = build_records(extracted_root)
    records = filter_by_date(records, start, coverage_start)
    records = dedup_by_content(records)
    return stage_records(records, out_dir)


def main() -> None:
    ap = argparse.ArgumentParser(description="Google Takeout → data/google_photos staging")
    ap.add_argument("--root", type=Path, default=_DEFAULT_ROOT)
    ap.add_argument("--start", type=lambda s: datetime.strptime(s, "%Y-%m-%d").date(),
                    default=date(2011, 1, 1), help="하한(포함), 기본 2011-01-01")
    ap.add_argument("--coverage-start", required=True,
                    type=lambda s: datetime.strptime(s, "%Y-%m-%d").date(),
                    help="상한 C(제외) = 맥 보관함 시작일")
    ap.add_argument("--skip-extract", action="store_true")
    args = ap.parse_args()

    raw, extracted = args.root / "raw", args.root / "extracted"
    if not args.skip_extract:
        extract_raw(raw, extracted)
    n = ingest(extracted, args.root, args.start, args.coverage_start)
    print(f"staged {n} photos → {args.root / 'staged'} (manifest.jsonl)")


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: 통과 확인 + 전체 스위트**

Run: `cd /Users/shingh/works/eddr && uv run pytest -v`
Expected: 모든 테스트 PASS

- [ ] **Step 6: Commit**

```bash
git -C /Users/shingh/works/eddr add src/eddr/google_takeout/ingest.py tests/conftest.py tests/google_takeout/test_ingest.py
git -C /Users/shingh/works/eddr commit -m "feat: Takeout 적재 오케스트레이터 + CLI + 통합 테스트

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 7 (게이트): 실데이터 검증 실행

⚠️ **선행 의존(사용자·구글):** 사용자가 Takeout에서 구글 포토 `[2011 … year(C)]` 연도앨범을 선택해 익스포트→다운로드하고, zip을 `data/google_photos/raw/`에 둔 뒤에만 실행 가능. 구글 처리 지연(수십 분~수시간) 때문에 **Task 2에서 C를 정한 직후 사용자가 익스포트를 먼저 걸어두는 것**이 좋다(그사이 Task 3–6 진행).

- [ ] **Step 1: 가장 작은 슬라이스로 라운드트립**

먼저 한 해(예: `Photos from 2011`)만 담은 작은 Takeout으로 실행:
Run: `cd /Users/shingh/works/eddr && uv run python -m eddr.google_takeout.ingest --coverage-start <C>`
Expected: `staged N photos …` 출력, `data/google_photos/staged/`에 파일·`manifest.jsonl` 생성.

- [ ] **Step 2: manifest 정합성 점검 (subagent로 위임)**

subagent(haiku)에게: manifest.jsonl 행수 = staged 파일수 확인, `taken_at`이 모두 `[2011, C)` 안인지, `latitude`/`description` 채움율, `taken_at` null 건수를 리포트하게 한다.

- [ ] **Step 3: 전량 실행 + 사용자 리뷰**

이상 없으면 전체 zip으로 실행하고, 최종 staged 장수·연도 분포를 사용자에게 보고. (메인 DB 통합은 별도 세션 — ADR-0005.)

---

## Self-Review

**1. Spec(ADR-0005) coverage:**
- "Takeout 수동 다운로드 → raw/" → Task 6 `extract_raw` + Task 7 선행. ✓
- "`[2011, C)` 날짜 필터, C=osxphotos 실측" → Task 2(C 측정), Task 4 `filter_by_date`, Task 6 CLI `--coverage-start`. ✓
- "교차 dedup·perceptual hash 미적용, 내부 중복만 BLAKE3" → Task 5 `dedup_by_content`(BLAKE3 only). perceptual hash 없음. ✓
- "메타 권위: 사이드카 우선, EXIF 폴백" → Task 4 `build_records`(사이드카 우선, `_exif_taken_at` 폴백). ✓
- "staged/ + manifest.jsonl" → Task 5 `stage_records`. ✓
- "source='google_takeout', source_uri=상대경로" → Task 5 manifest, Task 4 `source_uri`. ✓
- "프라이버시: data/ 비커밋" → Task 1 Step 1. ✓

**2. Placeholder scan:** 모든 코드 step에 실제 코드/명령/기대출력 포함. "적절한 에러처리" 류 없음. C는 Task 2에서 사용자 확정값으로 채워짐(런타임 입력, 플레이스홀더 아님). ✓

**3. Type consistency:** `MediaRecord`(walk.py)는 Task 4 정의 → Task 5·6에서 동일 필드 사용. `find_sidecar`/`parse_sidecar`(sidecar.py) → walk.py에서 사용. `blake3_hex`/`dedup_by_content`/`stage_records`(stage.py) → ingest.py에서 사용. `summarize_years`/`query_taken_dates`(coverage.py)는 Task 2 자체 완결. 시그니처 일치. ✓

**알려진 한계(의도적):** ① 사이드카 절단 매칭은 media명 접두사 기반 — media명 자체가 심하게 절단된 극단 케이스는 놓칠 수 있음(드묾, manifest의 taken_at null로 가시화). ② `dedup_by_content`이 파일을 두 번 해싱(빌드+스테이지) — 정확성 영향 없음, 대용량 성능 이슈 시 해시 캐시로 최적화. ③ taken_at은 UTC epoch 기준 — 날짜 경계의 tz 오차(±1일) 가능하나 [2011,C) 넓은 구간이라 영향 미미.
