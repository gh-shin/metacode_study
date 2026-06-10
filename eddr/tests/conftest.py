"""합성 Takeout 트리: 정상/중복/범위밖/절단 사이드카를 한 번에 재현."""

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


# 2015-08-15(in), 2009-01-01(범위밖 과거), 2023-08-15(범위밖 미래=overlap)
TS_2015, TS_2009, TS_2023 = "1439616078", "1230768000", "1692072078"


@pytest.fixture
def takeout_tree(tmp_path: Path) -> Path:
    root = tmp_path / "Takeout" / "Google Photos"
    # 정상 2015 (연도폴더) — geo/desc 포함
    _img(root / "Photos from 2015" / "IMG_A.jpg", (1, 2, 3))
    _sc(
        root / "Photos from 2015" / "IMG_A.jpg.supplemental-metadata.json",
        TS_2015,
        geoData={"latitude": 37.5, "longitude": 127.0},
        description="제주",
    )
    # 같은 사진이 앨범폴더에도 중복(바이트 동일) → dedup 대상
    _img(root / "여행앨범" / "IMG_A.jpg", (1, 2, 3))
    _sc(root / "여행앨범" / "IMG_A.jpg.supplemental-metadata.json", TS_2015)
    # 절단된 사이드카를 가진 2015 사진
    _img(root / "Photos from 2015" / "IMG_LONGNAME_0001.jpg", (4, 5, 6))
    _sc(root / "Photos from 2015" / "IMG_LONGNAME_0001.jpg.supplemental-metad.json", TS_2015)
    # 범위 밖(2009) — 하한 미만
    _img(root / "Photos from 2009" / "OLD.jpg", (7, 8, 9))
    _sc(root / "Photos from 2009" / "OLD.jpg.supplemental-metadata.json", TS_2009)
    # 범위 밖(2023) — 상한 이상(overlap 구간)
    _img(root / "Photos from 2023" / "NEW.jpg", (9, 9, 9))
    _sc(root / "Photos from 2023" / "NEW.jpg.supplemental-metadata.json", TS_2023)
    return tmp_path
