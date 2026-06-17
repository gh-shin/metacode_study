# Full-Dataset EDA Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `notebooks/02_full_dataset_eda.ipynb`를 만들어 iCloud 9,054(메타) ↔ local_photos 1,738(실픽셀)을 정합하고, 사진 자체 데이터(폴더·해상도·near-dup) insight를 산출하며, 다음 세션 Ollama용 근거 데이터(폴더구조 유지 썸네일 + 매니페스트)를 확보한다. **Ollama는 실행하지 않는다.**

**Architecture:** 단일 Jupyter 노트북(gitignored) + decode-once 스트리밍 파이프라인. 파일 1개당 디코드 1회로 BLAKE3·dHash·실해상도·썸네일을 동시 산출. 검증은 01_eda.ipynb 관례대로 셀 내 `assert`. 커밋 대상은 `docs/01_eda_findings.md`·`wiki/`뿐(노트북/데이터는 gitignore).

**Tech Stack:** Python 3.12 (`uv run`), osxphotos 0.75.9, pandas, numpy, Pillow 12 + pillow_heif, imagehash, blake3, matplotlib. 환경은 검증 완료(모든 import OK, HEIC opener 등록됨).

**Spec:** `docs/superpowers/specs/2026-06-03-full-dataset-eda-design.md`

---

## 사전 사실 (검증됨)

- iCloud: `PhotosDB()` → `library_path=/Users/shingh/Pictures/Photos Library.photoslibrary`, 9,054 assets(이미지 8,701 + 동영상 353), 100% iscloudasset, `path` 대부분 None(오프로드).
- osxphotos 필드: `uuid`, `original_filename`(예: `IMG_1127.HEIC`), `date`(tz-aware), `width`,`height`, `path`.
- local_photos: 1,738 분석가능 이미지(jpg 1268 + png 594 - 일부 + heic 62 등; PSB4·PSD5·ZIP5·동영상 제외), 28GB, 폴더는 여행/이벤트별(`2019_이탈리아/day01` 등).
- gitignore: `notebooks/*.ipynb`, `data/` → 노트북·썸네일·매니페스트 비커밋.

## File Structure

| 파일 | 상태 | 책임 |
|---|---|---|
| `notebooks/02_full_dataset_eda.ipynb` | Create (gitignored) | EDA 본체. 아래 셀들 |
| `data/eda_cache/local_files_meta.parquet` | Create (gitignored, runtime) | decode-once 산출 per-file 레코드 |
| `data/eda_cache/vision_manifest.parquet` | Create (gitignored, runtime) | 다음 세션 핸드오프 매니페스트(스키마 spec §9) |
| `data/eda_cache/thumbs/<rel>/*.jpg` | Create (gitignored, runtime) | 폴더구조 유지 썸네일 |
| `docs/01_eda_findings.md` | Modify (tracked) | 풀데이터셋 결과 섹션 추가 → **커밋** |
| `wiki/data-profile/eda-findings.md` | Modify (tracked) | INGEST 리프레시 → **커밋** |

> 노트북은 gitignore되므로 **이 plan이 코드의 git 보존본**이다. 셀 코드는 plan에 완전히 기재한다.

---

### Task 1: 노트북 스캐폴드 — config·imports·helpers

**Files:**
- Create: `notebooks/02_full_dataset_eda.ipynb`

- [ ] **Step 1: Cell 0 (config·imports) 작성**

```python
# ── 02 Full-Dataset EDA · config ───────────────────────────────────────────
import os, re, json, time
from pathlib import Path
import numpy as np, pandas as pd
from PIL import Image, ImageOps, ExifTags
import pillow_heif; pillow_heif.register_heif_opener()
import imagehash
from blake3 import blake3
import matplotlib.pyplot as plt
import matplotlib
matplotlib.rc("font", family="AppleGothic"); matplotlib.rcParams["axes.unicode_minus"] = False

PROJECT_DIR = Path.cwd().parent if Path.cwd().name == "notebooks" else Path.cwd()
DATA_DIR  = PROJECT_DIR / "data"
LOCAL_DIR = DATA_DIR / "local_photos"
CACHE_DIR = DATA_DIR / "eda_cache"; CACHE_DIR.mkdir(parents=True, exist_ok=True)
THUMB_DIR = CACHE_DIR / "thumbs"
IMG_EXTS  = {".jpg", ".jpeg", ".png", ".heic", ".heif"}
DHASH_SIZE = 8; NEAR_DUP_CUTOFF = 1; THUMB_MAX = 1024; JPEG_Q = 90; SEED = 42
np.random.seed(SEED)
print("PROJECT_DIR:", PROJECT_DIR); print("LOCAL_DIR exists:", LOCAL_DIR.exists())
```

- [ ] **Step 2: Cell 1 (pure helpers) 작성**

```python
# ── pure helpers (테스트 가능, IO 없음) ─────────────────────────────────────
# NOTE: [-_](\d+)$ 패턴 제거 — DSC_2881/FileJPEG-1075 등 고유번호를 복사번호로 오인하므로
_COPY_SUFFIX = re.compile(r"\s*\(\d+\)$|[-_]edited$|[-_]copy$", re.IGNORECASE)

def normalize_filename(name: str) -> str:
    """basename·대문자·확장자 제거·복사/편집 접미사 제거 → 매칭 키."""
    stem = Path(str(name)).stem
    prev = None
    while prev != stem:                      # 중첩 접미사 반복 제거: "IMG_1 (1)" 등
        prev = stem; stem = _COPY_SUFFIX.sub("", stem)
    return stem.upper().strip()

def parse_folder_date_hint(folder_top: str):
    """폴더명 앞자리 숫자에서 best-effort 날짜. 실패 시 None. (힌트 전용)"""
    m = re.match(r"^(\d{6})(?!\d)", folder_top)          # YYMMDD
    if m:
        yy, mm, dd = m.group(1)[:2], m.group(1)[2:4], m.group(1)[4:6]
        if "01" <= mm <= "12" and "01" <= dd <= "31":
            return f"20{yy}-{mm}-{dd}"
    m = re.match(r"^(20\d{2})(?!\d)", folder_top)         # YYYY
    if m: return m.group(1)
    return None

def hamming_matrix(dhash_hex: list[str]) -> np.ndarray:
    """dHash hex 리스트 → NxN Hamming 거리 행렬 (LUT popcount, 벡터화)."""
    arr = np.array([int(h, 16) for h in dhash_hex], dtype=np.uint64)
    b = arr.view(np.uint8).reshape(-1, 8)                 # (N,8)
    LUT = np.array([bin(i).count("1") for i in range(256)], dtype=np.uint8)
    xor = b[:, None, :] ^ b[None, :, :]                   # (N,N,8)
    return LUT[xor].sum(axis=2)                           # (N,N)
```

- [ ] **Step 3: Cell 2 (helper 검증 assert) 작성·실행**

```python
# ── helper self-check (01 관례: 인라인 assert) ──────────────────────────────
assert normalize_filename("IMG_1127.HEIC") == "IMG_1127"
assert normalize_filename("IMG_1127 (1).jpg") == "IMG_1127"
assert normalize_filename("DSCF7220-edited.psd") == "DSCF7220"
assert parse_folder_date_hint("181229_30_busan") == "2018-12-29"
assert parse_folder_date_hint("2019_이탈리아") == "2019"
assert parse_folder_date_hint("wedding") is None
_hm = hamming_matrix(["0000000000000000", "0000000000000001", "ffffffffffffffff"])
assert _hm[0, 1] == 1 and _hm[0, 0] == 0 and _hm[0, 2] == 64
print("helper asserts OK")
```

Run: 셀 실행. Expected: `helper asserts OK` 출력, 예외 없음.

- [ ] **Step 4: 노트북 저장 (체크포인트, 커밋 아님 — gitignored)**

Run: 노트북 저장(`jupyter`/에디터). 커밋하지 않는다(`notebooks/*.ipynb` gitignored).

---

### Task 2: §1 두 모집단 로드 (icloud_meta + local_files)

**Files:**
- Modify: `notebooks/02_full_dataset_eda.ipynb`
- Create (runtime): `data/eda_cache/icloud_meta.parquet`

- [ ] **Step 1: Cell 3 (icloud_meta 로드 + 캐시) 작성**

```python
# ── §1a. iCloud 메타 로드 (캐시 우선) ───────────────────────────────────────
ICLOUD_CACHE = CACHE_DIR / "icloud_meta.parquet"
if ICLOUD_CACHE.exists():
    icloud = pd.read_parquet(ICLOUD_CACHE)
else:
    import osxphotos
    db = osxphotos.PhotosDB()
    rows = []
    for p in db.photos(images=True, movies=False):
        rows.append({"uuid": p.uuid, "original_filename": p.original_filename,
                     "date": p.date, "width": p.width, "height": p.height,
                     "has_gps": p.location != (None, None) and p.location[0] is not None,
                     "lat": p.location[0], "lng": p.location[1],
                     "iscloudasset": p.iscloudasset, "path_local": p.path is not None})
    icloud = pd.DataFrame(rows)
    icloud.to_parquet(ICLOUD_CACHE)
icloud["fn_norm"] = icloud["original_filename"].map(normalize_filename)
print("icloud images:", len(icloud))
assert len(icloud) >= 8600, f"expected ~8701 images, got {len(icloud)}"
```

Run: 실행. Expected: `icloud images: ~8701`, assert 통과.

- [ ] **Step 2: Cell 4 (local_files walk) 작성**

```python
# ── §1b. local_photos walk → DataFrame ──────────────────────────────────────
recs = []
for f in sorted(LOCAL_DIR.rglob("*")):
    if not f.is_file() or f.suffix.lower() not in IMG_EXTS: continue
    rel = f.relative_to(LOCAL_DIR)
    recs.append({"local_path": str(f), "rel_path": str(rel),
                 "relative_folder": str(rel.parent), "folder_top": rel.parts[0],
                 "filename": f.name, "fn_norm": normalize_filename(f.name),
                 "ext": f.suffix.lower(), "bytes": f.stat().st_size})
local = pd.DataFrame(recs)
local["folder_date_hint"] = local["folder_top"].map(parse_folder_date_hint)
print("local analyzable images:", len(local))
assert len(local) > 1500, f"expected ~1738, got {len(local)}"
assert local["rel_path"].is_unique
display(local.groupby("ext").size().rename("n"))
```

Run: 실행. Expected: `local analyzable images: ~1738`, asserts 통과.

- [ ] **Step 3: 저장 (체크포인트)**

---

### Task 3: §0 폴더 taxonomy + §2 정합성

**Files:**
- Modify: `notebooks/02_full_dataset_eda.ipynb`

- [ ] **Step 1: Cell 5 (§0 폴더 taxonomy) 작성·실행**

```python
# ── §0. 폴더 분류 ──────────────────────────────────────────────────────────
tax = (local.groupby("folder_top")
       .agg(n_files=("filename", "size"),
            date_hint=("folder_date_hint", "first"),
            n_subfolders=("relative_folder", "nunique"))
       .sort_values("n_files", ascending=False))
print(f"최상위 폴더 수: {len(tax)} · 총 {tax['n_files'].sum()}장")
display(tax)
```

Run: 실행. Expected: 폴더별 파일 수 표, 합계 == len(local).

- [ ] **Step 2: Cell 6 (§2 정합성 매칭) 작성**

```python
# ── §2. 정합성: local ↔ icloud (fn_norm 매칭 + 날짜 tiebreak) ────────────────
icloud_keys = icloud[["fn_norm", "uuid", "date", "lat", "lng", "has_gps"]].copy()
icloud_keys = icloud_keys.rename(columns={"date": "icloud_date"})
m = local.merge(icloud_keys, on="fn_norm", how="left", indicator=True)

# 동일 fn_norm 다중 매칭은 중복행 발생 → local 1행당 best 1개로 축약(여기선 first)
m = m.sort_values(["local_path"]).drop_duplicates("local_path", keep="first")
m["match_confidence"] = np.where(m["_merge"] == "both", "medium", "none")  # 날짜비교는 Step3에서 high 승격
m["bucket"] = np.where(m["_merge"] == "both", "overlap", "icloud_new")
print(m["bucket"].value_counts())
print("\n매칭률:", (m["bucket"] == "overlap").mean().round(3))
```

Run: 실행. Expected: overlap/icloud_new 분포 출력.

- [ ] **Step 3: Cell 7 (EXIF GPS/date 보유율 + 신뢰도 승격) 작성**

```python
# ── §2b. 로컬 EXIF GPS/date 보유율 (사용자 가설 검증) ────────────────────────
_DATE_TAG = 36867   # DateTimeOriginal  (ExifIFD sub-IFD)
_GPS_TAG  = 34853   # GPSInfo           (IFD0)
_EXIF_IFD = 0x8769  # ExifIFD pointer
_GPS_IFD  = 0x8825  # GPSInfo pointer
def exif_probe(path):
    # NOTE: DateTimeOriginal(36867)은 ExifIFD(sub-IFD)에 있어 get_ifd()로 접근 필요
    try:
        with Image.open(path) as im: ex = im.getexif()
        gps_ifd = ex.get_ifd(_GPS_IFD)
        gps = bool(gps_ifd)
        exif_ifd = ex.get_ifd(_EXIF_IFD)
        dt = exif_ifd.get(_DATE_TAG)
        return gps, (dt if isinstance(dt, str) else None)
    except Exception:
        return False, None
probe = m["local_path"].map(exif_probe)
m["has_exif_gps"] = probe.map(lambda t: t[0])
m["exif_date"]    = probe.map(lambda t: t[1])
print("로컬 EXIF GPS 보유율:", m["has_exif_gps"].mean().round(3))
print("로컬 EXIF date 보유율:", m["exif_date"].notna().mean().round(3))
# 신뢰도 high 승격: 파일명 매칭 + EXIF date 존재
m.loc[(m["bucket"] == "overlap") & m["exif_date"].notna(), "match_confidence"] = "high"
display(m["match_confidence"].value_counts())
```

Run: 실행. Expected: GPS/date 보유율(가설대로 GPS 낮을 것), 신뢰도 분포.

- [ ] **Step 4: Cell 8 (출처 교차표 + 보정 풋프린트) 작성**

```python
# ── §2c. 출처 분할 & 보정 풋프린트 ──────────────────────────────────────────
def prefix(fn): 
    fn = fn.upper()
    return "IMG_" if fn.startswith("IMG_") else ("DSC/DSCF" if fn.startswith(("DSC_","DSCF")) else "기타")
m["prefix"] = m["filename"].map(prefix)
display(pd.crosstab(m["prefix"], m["bucket"]))
display(pd.crosstab(m["folder_top"], m["bucket"]))
n_new = int((m["bucket"] == "icloud_new").sum())
print(f"\n보정 총 풋프린트 = iCloud 9,054 ∪ iCloud-new {n_new} = {9054 + n_new} (메타 기준)")
print(f"'~10만' 대비 정정: 실측 약 {9054 + n_new:,}장")
```

Run: 실행. Expected: prefix×bucket 교차표(가설: DSC/DSCF가 icloud_new에 몰림), 보정 풋프린트.

- [ ] **Step 5: 저장 (체크포인트)**

---

### Task 4: §3 decode-once 파이프라인 (blake3 + dHash + 해상도 + 썸네일)

**Files:**
- Modify: `notebooks/02_full_dataset_eda.ipynb`
- Create (runtime): `data/eda_cache/thumbs/<rel>/*.jpg`, `data/eda_cache/local_files_meta.parquet`

- [ ] **Step 1: Cell 9 (decode-once 루프) 작성**

```python
# ── §3. decode-once: 파일 1개당 디코드 1회 → hash+해상도+썸네일 ──────────────
PIX_CACHE = CACHE_DIR / "local_files_meta.parquet"
FORCE_DECODE = False
if PIX_CACHE.exists() and not FORCE_DECODE:
    pix = pd.read_parquet(PIX_CACHE)
    print(f"decode 캐시 로드: {len(pix)} rows (재디코드 생략, FORCE_DECODE=True로 강제)")
else:
    def process_one(row):
        p = Path(row["local_path"]); rel = Path(row["rel_path"])
        out = {"local_path": str(p), "ok": False}
        try:
            data = p.read_bytes(); out["blake3"] = blake3(data).hexdigest()
            with Image.open(p) as im:
                im = ImageOps.exif_transpose(im).convert("RGB")
                out["width"], out["height"] = im.size
                out["dhash"] = str(imagehash.dhash(im, hash_size=DHASH_SIZE))
                thumb_path = THUMB_DIR / rel.parent / (rel.name + ".jpg")
                thumb_path.parent.mkdir(parents=True, exist_ok=True)
                t = im.copy(); t.thumbnail((THUMB_MAX, THUMB_MAX))
                t.save(thumb_path, "JPEG", quality=JPEG_Q)
                out["thumb_path"] = str(thumb_path)
            out["ok"] = True
        except Exception as e:
            out["error"] = repr(e)
        return out

    t0 = time.time()
    pix = pd.DataFrame([process_one(r) for _, r in local.iterrows()])
    elapsed = time.time() - t0
    print(f"decode-once: {pix['ok'].sum()}/{len(pix)} OK · {elapsed:.1f}s")
    if (~pix["ok"]).any(): display(pix[~pix["ok"]][["local_path", "error"]])
    pix.to_parquet(PIX_CACHE)

assert pix["ok"].mean() > 0.95, "디코드 실패율 과다 — 입력 점검"
```

Run: 실행. Expected: `~1738/1738 OK · ~Xs`(예상 5–8분), 실패<5%, parquet 저장.

- [ ] **Step 2: Cell 10 (썸네일 핸드오프 검증 assert) 작성·실행**

```python
# ── §3c-검증: 썸네일이 폴더구조 유지하며 생성됐는지 ──────────────────────────
ok = pix[pix["ok"]]
assert ok["thumb_path"].map(lambda p: Path(p).exists()).all(), "썸네일 누락"
# 폴더 미러링 확인: 임의 샘플의 thumb 상대경로 == 원본 상대경로(.jpg)
_s = ok.sample(min(5, len(ok)), random_state=SEED)
for _, r in _s.iterrows():
    rel_src = Path(r["local_path"]).relative_to(LOCAL_DIR)
    assert Path(r["thumb_path"]) == THUMB_DIR / rel_src.parent / (rel_src.name + ".jpg")
print("썸네일 폴더구조 유지 OK ·", len(ok), "장")
```

Run: 실행. Expected: `썸네일 폴더구조 유지 OK · ~1738장`.

- [ ] **Step 3: 저장 (체크포인트)**

---

### Task 5: §3a 해상도 + §3b near-duplicate 분석

**Files:**
- Modify: `notebooks/02_full_dataset_eda.ipynb`

- [ ] **Step 1: Cell 11 (§3a 해상도/품질) 작성·실행**

```python
# ── §3a. 실 해상도/품질 분포 ────────────────────────────────────────────────
ok = pix[pix["ok"]].copy()
ok["mp"] = (ok["width"] * ok["height"] / 1e6).round(1)
ok["aspect"] = (ok["width"] / ok["height"]).round(2)
print(ok["mp"].describe().round(2))
fig, ax = plt.subplots(1, 2, figsize=(13, 4))
ok["mp"].plot(kind="hist", bins=40, ax=ax[0]); ax[0].set_title("메가픽셀 분포")
ok["aspect"].plot(kind="hist", bins=40, ax=ax[1]); ax[1].set_title("종횡비 분포")
plt.tight_layout(); plt.show()
```

Run: 실행. Expected: 해상도 통계 + 히스토그램.

- [ ] **Step 2: Cell 12 (§3b near-dup: exact + dHash 분포) 작성·실행**

```python
# ── §3b. 실 near-duplicate (D8) ─────────────────────────────────────────────
exact = ok[ok.duplicated("blake3", keep=False)]
print(f"BLAKE3 정확중복 파일: {len(exact)} ({exact['blake3'].nunique()} 그룹)")

H = hamming_matrix(ok["dhash"].tolist())                 # (N,N)
iu = np.triu_indices(len(ok), k=1)
dist = H[iu]
plt.figure(figsize=(8, 4))
plt.hist(dist, bins=range(0, 66, 2)); plt.axvline(NEAR_DUP_CUTOFF + 0.5, color="red", ls="--")
plt.title("pairwise dHash Hamming (실데이터 1,738장)"); plt.xlabel("Hamming"); plt.show()
nd = int((dist <= NEAR_DUP_CUTOFF).sum())
print(f"near-dup 쌍 (≤{NEAR_DUP_CUTOFF}): {nd} · 전체 쌍의 {nd/len(dist):.4%}")
```

Run: 실행. Expected: 정확중복 수, Hamming 히스토그램, **실 near-dup율**(01에서 미측정이던 값).

- [ ] **Step 3: Cell 13 (§3b cross-folder 중복) 작성·실행**

```python
# ── §3b-2. cross-folder 중복 (같은 사진이 여러 여행폴더에) ───────────────────
ok2 = ok.merge(local[["local_path", "folder_top"]], on="local_path")
i, j = iu
pairs = pd.DataFrame({"a": i[dist <= NEAR_DUP_CUTOFF], "b": j[dist <= NEAR_DUP_CUTOFF]})
pairs["fa"] = ok2.iloc[pairs["a"]]["folder_top"].values
pairs["fb"] = ok2.iloc[pairs["b"]]["folder_top"].values
cross = pairs[pairs["fa"] != pairs["fb"]]
print(f"cross-folder near-dup 쌍: {len(cross)} / 전체 near-dup {len(pairs)}")
if len(cross): display(cross.groupby(["fa", "fb"]).size().sort_values(ascending=False).head(10))
```

Run: 실행. Expected: 폴더 간 중복 쌍 수.

- [ ] **Step 4: 저장 (체크포인트)**

---

### Task 6: §3c vision_manifest.parquet 조립 + 핸드오프 검증

**Files:**
- Modify: `notebooks/02_full_dataset_eda.ipynb`
- Create (runtime): `data/eda_cache/vision_manifest.parquet`

- [ ] **Step 1: Cell 14 (매니페스트 조립, spec §9 스키마) 작성**

```python
# ── §3c. vision_manifest 조립 (다음 세션 Ollama 입력) ───────────────────────
man = (local[["local_path", "fn_norm", "relative_folder", "folder_top", "folder_date_hint"]]
       .merge(m[["local_path", "exif_date", "has_exif_gps", "lat", "lng",
                 "uuid", "match_confidence", "bucket"]], on="local_path", how="left")
       .merge(pix[["local_path", "thumb_path", "width", "height", "blake3", "dhash", "ok"]],
              on="local_path", how="left"))
man = man.rename(columns={"fn_norm": "filename_norm", "uuid": "matched_uuid",
                          "lat": "gps_lat", "lng": "gps_lng"})
man = man[man["ok"] == True].drop(columns=["ok"])
COLS = ["local_path","thumb_path","filename_norm","relative_folder","folder_top",
        "folder_date_hint","exif_date","has_exif_gps","gps_lat","gps_lng",
        "matched_uuid","match_confidence","width","height","blake3","dhash","bucket"]
man = man[COLS]
man.to_parquet(CACHE_DIR / "vision_manifest.parquet")
print("manifest rows:", len(man)); display(man.head())
```

Run: 실행. Expected: 매니페스트 head, parquet 저장.

- [ ] **Step 2: Cell 15 (핸드오프 검증 assert) 작성·실행**

```python
# ── §3c-검증: 매니페스트가 다음 세션을 제대로 unblock 하는지 ─────────────────
man2 = pd.read_parquet(CACHE_DIR / "vision_manifest.parquet")
assert list(man2.columns) == COLS, "스키마 불일치"
assert len(man2) == int(pix["ok"].sum()), "row 수 불일치"
assert man2["thumb_path"].map(lambda p: Path(p).exists()).all(), "썸네일 경로 깨짐"
assert man2["folder_top"].notna().all(), "폴더 컨텍스트 누락"
print("핸드오프 매니페스트 검증 OK:", len(man2), "행 ·", man2["bucket"].value_counts().to_dict())
```

Run: 실행. Expected: `핸드오프 매니페스트 검증 OK ...`.

- [ ] **Step 3: 저장 (체크포인트)**

---

### Task 7: §5 findings 갱신 + wiki 리프레시 (커밋 대상)

**Files:**
- Modify: `docs/01_eda_findings.md` (tracked)
- Modify: `wiki/data-profile/eda-findings.md` (tracked)

- [ ] **Step 1: Cell 16 (findings용 수치 요약 출력) 작성·실행**

```python
# ── §5. findings 기재용 핵심 수치 한 곳에 ───────────────────────────────────
summary = {
    "local_analyzable": len(local),
    "overlap": int((m["bucket"] == "overlap").sum()),
    "icloud_new": int((m["bucket"] == "icloud_new").sum()),
    "corrected_footprint": 9054 + int((m["bucket"] == "icloud_new").sum()),
    "local_exif_gps_rate": round(float(m["has_exif_gps"].mean()), 3),
    "exact_dup_files": int(len(exact)),
    "near_dup_pairs": int((dist <= NEAR_DUP_CUTOFF).sum()),
    "near_dup_rate": round(float((dist <= NEAR_DUP_CUTOFF).mean()), 6),
    "median_mp": float(ok["mp"].median()),
    "decode_ok": int(pix["ok"].sum()),
}
print(json.dumps(summary, ensure_ascii=False, indent=2))
```

Run: 실행. Expected: 수치 JSON. **이 값들을 Step 2에 전사.**

- [ ] **Step 2: `docs/01_eda_findings.md`에 섹션 추가**

문서 끝에 `## 7. 풀데이터셋 EDA (02 notebook, 2026-06-03)` 섹션을 추가하고 Step 1 수치를 기재. 포함: 보정 풋프린트(~10만 정정), overlap/icloud_new, 로컬 EXIF GPS 보유율, **실 near-dup율(D8 근거)**, 해상도 중앙값, 출처분할 요지, 다음 세션 핸드오프(썸네일+매니페스트) 준비 완료. ADR flag 3건(스케일 정정 / iCloud-new의 D12·D16 영향 / D8 재검토) 명시 — 결정은 사용자 몫으로 표기.

- [ ] **Step 3: `wiki/data-profile/eda-findings.md` INGEST 리프레시**

frontmatter `last_verified: 2026-06-03`, `status: fresh`로 갱신. 9,047→9,054 및 풀데이터셋 핵심 수치 반영. `source`에 `docs/01_eda_findings.md` 유지. (AGENTS.md INGEST 절차)

- [ ] **Step 4: 커밋 (tracked 문서만)**

```bash
git add docs/01_eda_findings.md wiki/data-profile/eda-findings.md
git commit -m "docs: 풀데이터셋 EDA 결과 — 보정 풋프린트·실 near-dup율·다음세션 핸드오프

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

Run: 커밋. Expected: 2 files changed. (노트북·매니페스트·썸네일은 gitignore라 미포함 — 정상)

---

## Self-Review

**1. Spec coverage:**
- spec §1 데이터모델 → Task 2 ✓ / §0 taxonomy → Task 3 Step1 ✓ / §2 정합성(버킷·prefix·folder·EXIF율·풋프린트) → Task 3 ✓ / §3a 해상도 → Task 5 ✓ / §3b near-dup(분포·cutoff·cross-folder) → Task 5 ✓ / §3c 썸네일 미러링+매니페스트 → Task 4·6 ✓ / §4 decode-once·파일크기 → Task 4 ✓ / §5 산출물·findings·ADR flag → Task 7 ✓ / §6 완료기준 5개 → Task 3·5·6 asserts ✓ / §7 에러처리(flag·skip·seed) → Task 4 try/except·SEED ✓ / §9 매니페스트 스키마 → Task 6 COLS ✓.
- **gap 없음.** (비범위 §8 Ollama/비전 brige는 의도적 제외 — Task에 없음 = 정상.)

**2. Placeholder scan:** 모든 코드 셀 완전 기재. Task 7 Step2/3만 산문 지시(문서 작성은 Step1 수치 전사 — 수치는 런타임 산출이라 코드로 출력 후 전사가 올바름, placeholder 아님).

**3. Type consistency:** `fn_norm`(local)↔`fn_norm`(icloud) 머지 키 일치. `bucket` 값 `overlap`/`icloud_new` 전 Task 일관. `pix`/`m`/`local`/`man` 머지 키 `local_path` 일관. `hamming_matrix` 반환 (N,N) → `H[iu]` 사용 일관. 매니페스트 `COLS`가 spec §9와 일치(local_path, thumb_path, filename_norm, relative_folder, folder_top, folder_date_hint, exif_date, has_exif_gps, gps_lat, gps_lng, matched_uuid, match_confidence, width, height, blake3, dhash, bucket).

**해결한 이슈:** §2 매칭에서 동일 `fn_norm` 다중 매칭 → `drop_duplicates("local_path")`로 local 1행당 1매칭 보장(merge 폭증 방지).

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-06-03-full-dataset-eda.md`.**
