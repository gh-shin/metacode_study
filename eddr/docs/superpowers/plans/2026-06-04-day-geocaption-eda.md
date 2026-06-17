# Day-level 장소추정 캡션 보강 EDA — 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development 또는 superpowers:executing-plans로 task별 구현. 단, 본 계획은 **EDA 노트북**이라 §1 스모크 판정과 §4 환각 정성검토는 사람이 응답을 보고 판단한다(자동 완주 불가) — Task 2 종료 후·Task 5 후반에 사용자 개입점이 있다.

**Goal:** 03 핸드오프(manifest+thumbs)와 03 평가풀 캡션을 재사용해, `gemma4:26b`의 day-묶음 multi-image coarse 지명 추정을 e2b 캡션에 주입했을 때 03의 지명 약점(제주·일산 recall 0.00)이 메워지는지를, 공격/보수 A/B로 정량 비교해 findings에 남긴다.

**Architecture:** `notebooks/04_day_geocaption_eda.ipynb`(gitignore) 단일 노트북. §0 셋업 → §1 multi-image 스모크 게이트(실패 시 montage fallback) → §2 폴더→day 그룹핑·대표 6장 multi-image 지명추정(공격/보수) → §3 day-place 전파·e2b 캡션 결합·임베딩(비교군 3) → §4 recall + day-place 정확도·환각율 → findings 갱신. place·임베딩은 parquet 캐시로 재실행 저렴.

**Tech Stack:** Jupyter, pandas/pyarrow, Pillow(+pillow-heif, ImageOps), numpy, `ollama` python client, 로컬 Ollama(`gemma4:26b`/`gemma4:e2b`/`qwen3-embedding:8b`), `unicodedata`(NFC).

**검증 전략(EDA 완화):** pytest 대신 **노트북 inline `assert`(순수 함수) + 셀 실행–관찰**. 순수 로직(montage 합성·그룹핑·대표샘플·recall@k·place alias 매칭)만 합성 입력 assert로 잠근다. 추정 품질·스모크 판정은 사람 판단. 근거: EDA는 게이트 아닌 insight(프로젝트 규약).

---

## File Structure

- **Create**: `notebooks/04_day_geocaption_eda.ipynb` — 본 EDA 노트북 (gitignore)
- **Read(재사용)**: `data/eda_cache/vision_manifest.parquet`(1,737행), `data/eda_cache/thumbs/<폴더>/*.jpg`, `data/eda_cache/pool_captions_03.parquet`(03 평가풀 e2b 장면캡션)
- **Create(캐시)**: `data/eda_cache/day_places_04.parquet`(그룹별 공격/보수 지명), `data/eda_cache/pool_embeddings_04.parquet`(비교군 3 임베딩)
- **Modify**: `docs/01_eda_findings.md`(§9 추가), `wiki/data-profile/eda-findings.md`, `wiki/models/model-decisions.md`, `TODO.md`, `TODO_ARCHIVE.md`

> 노트북 셀은 `NotebookEdit`로 추가한다. 아래 각 Task의 "Cell" = 노트북에 추가할 셀 1개. 노트북·캐시는 gitignore라 커밋하지 않는다(ADR-0001).

---

## Task 1: §0 셋업 — imports·Ollama 연결·03 자산 로드

**Files:** Create `notebooks/04_day_geocaption_eda.ipynb`

- [ ] **Step 1: 마크다운 헤더 셀**

```markdown
# 04 — Day-level 장소추정 캡션 보강 EDA
spec: docs/superpowers/specs/2026-06-04-day-geocaption-eda-design.md
입력: 03 핸드오프(vision_manifest.parquet + thumbs/ + pool_captions_03.parquet).
가설: 26b day-묶음 multi-image coarse 지명 → e2b 캡션 주입 → 03 지명약점(제주·일산 0.00) 보완.
전부 로컬 Ollama, 외부 전송 0(ADR-0001).
```

- [ ] **Step 2: 셋업 코드 셀 — imports·경로·seed·모델**

```python
import json, time, random, re, unicodedata
from pathlib import Path
import numpy as np
import pandas as pd
from PIL import Image, ImageOps
import pillow_heif; pillow_heif.register_heif_opener()
import ollama

SEED = 42
random.seed(SEED); np.random.seed(SEED)

ROOT = Path.cwd().parent if Path.cwd().name == "notebooks" else Path.cwd()
CACHE = ROOT / "data" / "eda_cache"
MANIFEST = CACHE / "vision_manifest.parquet"
THUMB_DIR = CACHE / "thumbs"
POOL_CAP_03 = CACHE / "pool_captions_03.parquet"   # 03 평가풀 e2b 장면캡션

GEO_MODEL = "gemma4:26b"      # day-place 장소추정(사용자 지목, 지리 사전지식)
SCENE_MODEL = "gemma4:e2b"    # 03 장면캡션(재사용; 재생성 시 폴백용)
EMB_MODEL = "qwen3-embedding:8b"
```

- [ ] **Step 3: Ollama 연결·모델 존재 확인 셀**

```python
installed = {x.model for x in ollama.list().models}
need = {GEO_MODEL, SCENE_MODEL, EMB_MODEL}
missing = need - installed
assert not missing, f"누락 모델: {missing} — ollama pull 필요"
print("Ollama OK:", sorted(need))
```

Run: 셀 실행. Expected: `Ollama OK: ['gemma4:26b', 'gemma4:e2b', 'qwen3-embedding:8b']`.

- [ ] **Step 4: manifest + 03 평가풀 캡션 로드·sanity 셀**

```python
m = pd.read_parquet(MANIFEST)
assert len(m) == 1737, len(m)
assert m["thumb_path"].notna().all()

assert POOL_CAP_03.exists(), \
    "03 평가풀 캡션 없음 — notebooks/03_vision_caption_eda.ipynb의 풀 캡션 셀을 먼저 실행"
pool03 = pd.read_parquet(POOL_CAP_03)
pool03 = pool03[["thumb_path", "folder_top", "caption"]].drop_duplicates("thumb_path")
assert pool03["caption"].notna().all() and len(pool03) >= 300, len(pool03)
print(f"manifest {len(m)} · 03 평가풀 캡션 {len(pool03)}장 (e2b 장면캡션 재사용)")
```

Run: 셀 실행. Expected: `manifest 1737 · 03 평가풀 캡션 ~400장`. 03 캡션 없으면 assert가 03 선행을 지시.

---

## Task 2: §1 multi-image 종합추론 스모크 게이트 + montage fallback

**Files:** Modify `notebooks/04_day_geocaption_eda.ipynb`

- [ ] **Step 1: montage 합성 순수 함수 셀(fallback용 — 미리 정의)**

```python
def montage(thumb_paths, cols=3, cell=384):
    """N장을 cols 그리드 1장으로 합성. multi-image FAIL 시 단일 입력 폴백."""
    paths = list(thumb_paths); n = len(paths); rows = (n + cols - 1) // cols
    canvas = Image.new("RGB", (cols*cell, rows*cell), (16, 16, 16))
    for i, tp in enumerate(paths):
        im = ImageOps.contain(Image.open(tp).convert("RGB"), (cell, cell))
        x = (i % cols)*cell + (cell - im.width)//2
        y = (i // cols)*cell + (cell - im.height)//2
        canvas.paste(im, (x, y))
    out = CACHE / "_montage_tmp.jpg"; canvas.save(out, quality=88)
    return str(out)
```

- [ ] **Step 2: montage inline assert 셀(합성 입력)**

```python
_p = []
for i, c in enumerate([(200,0,0),(0,200,0),(0,0,200)]):
    q = CACHE / f"_smk_{i}.jpg"; Image.new("RGB",(64,48),c).save(q); _p.append(str(q))
_mp = montage(_p, cols=3, cell=384)
_mi = Image.open(_mp)
assert _mi.size == (3*384, 1*384), _mi.size      # 3장→1행3열
assert montage(_p[:1]).__class__ is str          # 1장도 동작
print("montage assert OK", _mi.size)
for q in _p: Path(q).unlink()
```

Run: 셀 실행. Expected: `montage assert OK (1152, 384)`.

- [ ] **Step 3: 스모크 테스트 셀 — 서로 다른 2장 종합추론 확인**

```python
# 서로 다른 폴더(=다른 장소) 1장씩 골라 묶음 입력 → 두 장면을 모두 인식하는지
two = (m.sort_values("folder_top").groupby("folder_top").head(1)
         .sample(2, random_state=SEED))
smoke_imgs = two["thumb_path"].tolist()
SMOKE_PROMPT = ("You are shown multiple photos at once. Briefly describe EACH photo "
    "separately as a numbered list (1., 2., ...). Do not merge them.")
r = ollama.chat(model=GEO_MODEL,
    messages=[{"role":"user","content":SMOKE_PROMPT,"images":smoke_imgs}],
    options={"seed":SEED})
resp = r["message"]["content"]
print("입력:", [Path(p).name for p in smoke_imgs]); print("---\n", resp)
```

Run: 셀 실행(26b 콜드 ~33s). Expected: 응답 출력. **2개 항목(1., 2.)이 서로 다른 장면을 기술하면 multi-image 종합추론 PASS.**

- [ ] **Step 4: 스모크 판정 셀(휴리스틱 + 사람 확인)**

```python
# 휴리스틱: 번호목록 2개 이상 + 길이. 최종은 사람이 위 응답 보고 확정.
auto = bool(re.search(r"(?m)^\s*2[\.\)]", resp)) and len(resp) > 80
MULTI_IMAGE_OK = auto   # ← 위 응답이 두 장면을 따로 기술하면 True 유지, 아니면 False로 수정
print(f"휴리스틱 multi-image PASS={auto} → MULTI_IMAGE_OK={MULTI_IMAGE_OK}")
print("FAIL이면 montage fallback으로 진행(품질 동등, 해상도만 손실).")
```

Run: 셀 실행. Expected: `MULTI_IMAGE_OK` 확정.

> ⚠️ **사용자 개입점**: Step 3 응답이 두 장면을 따로 기술했는지 눈으로 확인하고 `MULTI_IMAGE_OK`를 확정한다(휴리스틱이 틀리면 직접 True/False 수정). 이 값이 Task 3 추정 입력 방식을 결정한다.

---

## Task 3: §2 폴더→day 그룹핑 + day-place 추정 (공격/보수 A/B)

**Files:** Modify `notebooks/04_day_geocaption_eda.ipynb`; Create `data/eda_cache/day_places_04.parquet`

- [ ] **Step 1: 그룹핑 + 대표샘플 순수 함수 셀**

```python
def day_groups(df):
    """folder_top → (exif_date 있으면) 날짜 세분. 날짜 결손은 폴더 1그룹."""
    d = df.copy()
    dt = pd.to_datetime(d.get("exif_date"), errors="coerce")
    d["day"] = dt.dt.strftime("%Y-%m-%d")
    d["group_key"] = np.where(d["day"].notna(),
                              d["folder_top"] + "|" + d["day"].fillna(""),
                              d["folder_top"])
    d["_sort"] = dt
    return d

def rep_sample(g, n=6):
    """그룹 내 시간순 균등 N장(하루 대표). 날짜 없으면 입력순. 결정적."""
    g = g.sort_values("_sort", na_position="last")
    if len(g) <= n: return g
    idx = np.linspace(0, len(g)-1, n).round().astype(int)
    return g.iloc[np.unique(idx)]
```

- [ ] **Step 2: 그룹핑·대표샘플 inline assert 셀(합성 입력)**

```python
_df = pd.DataFrame({
    "folder_top": ["A"]*8 + ["B"]*2,
    "exif_date": ["2020-01-01"]*4 + ["2020-01-02"]*4 + [None, None],
    "thumb_path": [f"t{i}" for i in range(10)],
})
_g = day_groups(_df)
assert set(_g["group_key"]) == {"A|2020-01-01", "A|2020-01-02", "B"}, set(_g["group_key"])
_r = rep_sample(_g[_g.group_key=="A|2020-01-01"], n=6)
assert len(_r) == 4                          # 4장뿐이면 전량
_r2 = rep_sample(_g[_g.group_key=="A|2020-01-01"].iloc[[0]*10].assign(_sort=range(10)), n=6)
assert len(_r2) == 6                          # 10장→6장
print("day_groups / rep_sample assert OK")
```

Run: 셀 실행. Expected: `day_groups / rep_sample assert OK`.

- [ ] **Step 3: coarse 지명 프롬프트 A/B + 추정 함수 셀**

```python
GEO_PROMPTS = {
  "aggressive": ("These photos are all from the SAME day or trip. Using only visual clues "
    "(terrain, vegetation, architecture, skyline, signage script, sky/light), infer the SINGLE "
    "most likely location at COARSE granularity (city or province + country). You MUST make your "
    "best guess even if uncertain. Reply with ONLY the place name, e.g. 'Jeju Island, South Korea'."),
  "conservative": ("These photos are all from the SAME day or trip. If the location is clearly "
    "identifiable from visual clues at COARSE granularity (city or province + country), reply with "
    "ONLY that place name; otherwise reply with exactly 'unknown'. Do not guess wildly."),
}

def estimate_place(thumb_paths, prompt, multi_ok):
    """multi_ok면 N장 직접 입력, 아니면 montage 1장. flag-skip."""
    try:
        imgs = list(thumb_paths) if multi_ok else [montage(thumb_paths)]
        r = ollama.chat(model=GEO_MODEL,
            messages=[{"role":"user","content":prompt,"images":imgs}], options={"seed":SEED})
        return r["message"]["content"].strip().splitlines()[0][:120]
    except Exception as e:
        return f"__ERR__:{e}"
```

> 주의: `thumb_paths`만 입력 — **folder_top/지명 텍스트는 절대 프롬프트에 넣지 않는다**(정답 누출 차단, spec §3).

- [ ] **Step 4: 평가풀 커버 그룹만 추정 + 캐시 셀**

```python
PLACES = CACHE / "day_places_04.parquet"
poolm = day_groups(m[m.thumb_path.isin(pool03.thumb_path)])   # 03 풀이 덮는 사진만
if PLACES.exists():
    places = pd.read_parquet(PLACES)
else:
    recs, t0 = [], time.time()
    for gk, g in poolm.groupby("group_key"):
        reps = rep_sample(g, 6)
        rec = {"group_key": gk, "folder_top": g["folder_top"].iloc[0], "n": len(g)}
        for strat, ptext in GEO_PROMPTS.items():
            rec[strat] = estimate_place(reps["thumb_path"].tolist(), ptext, MULTI_IMAGE_OK)
        recs.append(rec)
    places = pd.DataFrame(recs); places.to_parquet(PLACES)
    errs = places[["aggressive","conservative"]].apply(lambda s: s.str.startswith("__ERR__")).sum().sum()
    print(f"{len(places)} 그룹 추정 · {time.time()-t0:.0f}s · 에러 {int(errs)}")
print(places[["group_key","n","aggressive","conservative"]].head(20).to_string())
```

Run: 셀 실행(26b multi-image × 그룹수 × 2). Expected: 그룹별 (공격/보수) 지명 표 + wall-clock. 추정 지명이 폴더와 그럴듯하게 맞는지 눈으로 관찰.

---

## Task 4: §3 day-place 전파 · e2b 캡션 결합 · 임베딩 (비교군 3)

**Files:** Modify `notebooks/04_day_geocaption_eda.ipynb`; Create `data/eda_cache/pool_embeddings_04.parquet`

- [ ] **Step 1: 결합 + 임베딩 함수 셀**

```python
def combine(scene_cap, place):
    """e2b 장면캡션 + Location 줄. unknown/에러/빈값은 미부착(=기준선과 동일)."""
    p = (place or "").strip()
    if not p or p.lower() == "unknown" or p.startswith("__ERR__"):
        return scene_cap
    return f"{scene_cap}\nLocation: {p}"

def embed(text):   # 03과 동일 시그니처
    return np.asarray(ollama.embed(model=EMB_MODEL, input=text).embeddings[0], dtype=np.float32)
```

- [ ] **Step 2: combine inline assert 셀**

```python
assert combine("a cat", "Jeju Island, South Korea") == "a cat\nLocation: Jeju Island, South Korea"
assert combine("a cat", "unknown") == "a cat"
assert combine("a cat", "__ERR__:x") == "a cat"
assert combine("a cat", "") == "a cat"
print("combine assert OK")
```

Run: 셀 실행. Expected: `combine assert OK`.

- [ ] **Step 3: 비교군 3 텍스트 생성 셀**

```python
poolj = (poolm.merge(places[["group_key","aggressive","conservative"]], on="group_key", how="left")
              .merge(pool03[["thumb_path","caption"]], on="thumb_path", how="left"))
assert poolj["caption"].notna().all(), "03 캡션 매칭 실패 thumb 존재"
poolj["text_base"] = poolj["caption"]                                              # e2b 단독(기준선)
poolj["text_aggr"] = [combine(c,p) for c,p in zip(poolj.caption, poolj.aggressive)]  # +place 공격
poolj["text_cons"] = [combine(c,p) for c,p in zip(poolj.caption, poolj.conservative)]# +place 보수
print("place 부착률 · 공격:", (poolj.text_aggr!=poolj.text_base).mean().round(3),
      "· 보수:", (poolj.text_cons!=poolj.text_base).mean().round(3))
```

Run: 셀 실행. Expected: 부착률 출력(공격 ≥ 보수 예상).

- [ ] **Step 4: 비교군 3 임베딩 생성·캐시 셀**

```python
EMB = CACHE / "pool_embeddings_04.parquet"
if EMB.exists():
    emb_df = pd.read_parquet(EMB)
else:
    t0 = time.time()
    for col in ["text_base","text_aggr","text_cons"]:
        poolj[col+"_emb"] = [embed(t).tolist() for t in poolj[col]]
    emb_df = poolj; emb_df.to_parquet(EMB)
    print(f"임베딩 {len(emb_df)}×3 · {time.time()-t0:.0f}s")
assert all(c in emb_df for c in ["text_base_emb","text_aggr_emb","text_cons_emb"])
```

Run: 셀 실행. Expected: 비교군 3 임베딩 캐시.

---

## Task 5: §4 recall + day-place 정확도·환각율

**Files:** Modify `notebooks/04_day_geocaption_eda.ipynb`

- [ ] **Step 1: 한국어 질의셋 셀(03 재사용 — 지명질의 반드시 포함)**

```python
# 03 노트북 질의셋과 일치시킨다(노트북 우선). 핵심: 03에서 0.00이던 지명질의 포함.
QUERIES = {
  "결혼식 사진": "wedding",
  "아이슬란드 여행": "2022_아이슬란드",
  "이탈리아 여행": "2019_이탈리아",
  "방콕 여행": "bangkok",
  "개심사": "개심사",
  "제주도에서 찍은 사진": "200620_23_제주",   # 03 recall@10 0.00 (지명약점)
  "일산 호수공원": "일산호수공원",            # 03 recall@10 0.00 (지명약점)
}
GEO_QUERIES = ["제주도에서 찍은 사진", "일산 호수공원"]   # 보강 효과 집중 측정 대상
folders = set(pool03["folder_top"]) | set(m["folder_top"])
miss = [v for v in QUERIES.values() if v not in folders]
assert not miss, f"정답 폴더 불일치(03 노트북 폴더명과 맞출 것, NFC 주의): {miss}"
print(len(QUERIES), "질의 · 지명질의:", GEO_QUERIES)
```

Run: 셀 실행. Expected: 질의 검증 통과. 불일치 시 assert가 폴더명(NFD/NFC·표기)을 지시 → 03 노트북 값과 일치시킨다.

- [ ] **Step 2: recall@k 순수 함수 + assert 셀(03과 동일)**

```python
def recall_mrr(q_emb, pool_embs, pool_labels, gold, ks=(5,10)):
    sims = pool_embs @ q_emb / (np.linalg.norm(pool_embs,axis=1)*np.linalg.norm(q_emb)+1e-9)
    order = np.argsort(-sims)
    hits = [i for i,idx in enumerate(order) if pool_labels[idx]==gold]
    rr = 1.0/(hits[0]+1) if hits else 0.0
    return {f"recall@{k}": float(any(h < k for h in hits)) for k in ks} | {"mrr": rr}

_pe = np.array([[1,0],[0,1],[0.9,0.1]], dtype=np.float32)
_r = recall_mrr(np.array([1,0],dtype=np.float32), _pe, ["g","x","g"], "g")
assert _r["recall@5"]==1.0 and abs(_r["mrr"]-1.0)<1e-6, _r
print("recall_mrr assert OK")
```

Run: 셀 실행. Expected: `recall_mrr assert OK`.

- [ ] **Step 3: 비교군 3 × 질의 recall 셀**

```python
ARMS = {"e2b_base":"text_base_emb", "+place_aggr":"text_aggr_emb", "+place_cons":"text_cons_emb"}
rows = []
for arm, col in ARMS.items():
    P = np.array(emb_df[col].tolist(), dtype=np.float32); labels = emb_df["folder_top"].tolist()
    for q, gold in QUERIES.items():
        rows.append({"arm":arm, "query":q, **recall_mrr(embed(q), P, labels, gold)})
res = pd.DataFrame(rows)
print("== 비교군 평균 =="); print(res.groupby("arm")[["recall@5","recall@10","mrr"]].mean().round(3))
print("\n== 지명질의 recall@10 (보강 효과) ==")
print(res[res["query"].isin(GEO_QUERIES)].pivot_table(index="query", columns="arm", values="recall@10"))
```

Run: 셀 실행. Expected: 비교군 평균 + **지명질의(제주·일산)가 e2b_base 0.00 대비 +place에서 오르는지**. arm 순서 보존 위해 출력 확인.

- [ ] **Step 4: day-place 정확도·환각율 셀(alias 규칙 + 정성)**

```python
# 영어 추정 ↔ 한글/영문 폴더 약(弱)매칭. 미수록 지명은 정성검토 대상으로 남긴다.
PLACE_ALIAS = {
  "jeju":"제주", "iceland":"아이슬란드", "italy":"이탈리아", "bangkok":"bangkok",
  "ilsan":"일산", "seoul":"서울", "busan":"busan", "mongolia":"몽골",
  "gangneung":"강릉", "gaesimsa":"개심사",
}  # 필요 시 폴더에 등장하는 지명 추가
def place_hit(place, folder_top):
    f = unicodedata.normalize("NFC", str(folder_top)).lower(); pl = str(place).lower()
    for en, ko in PLACE_ALIAS.items():
        if en in pl and (en in f or ko in f): return True
    return False

ev = places.copy()
for strat in ["aggressive","conservative"]:
    named = ~ev[strat].str.lower().isin(["unknown"]) & ~ev[strat].str.startswith("__ERR__")
    hit = ev.apply(lambda r: place_hit(r[strat], r["folder_top"]), axis=1)
    n_named = int(named.sum())
    print(f"[{strat}] 추정시도 {n_named}/{len(ev)} · 적중(alias) {int((named&hit).sum())} "
          f"· 미적중(환각후보) {int((named&~hit).sum())} · unknown {int((~named).sum())}")
print("\n== 환각 후보(추정했으나 alias 불일치) — 정성검토 ==")
print(ev[named & ~ev.apply(lambda r: place_hit(r['aggressive'], r['folder_top']), axis=1)]
        [["group_key","folder_top","aggressive"]].head(20).to_string())
```

Run: 셀 실행. Expected: 공격/보수별 적중·환각후보·unknown 카운트 + 환각 후보 표.

> ⚠️ **사용자 개입점**: alias 미수록 지명이 있을 수 있으므로, "환각 후보" 표를 눈으로 검토해 진짜 환각인지(폴더와 무관한 틀린 지명) 확인한다. 공격 vs 보수의 recall 이득과 환각율을 함께 보고 권고를 정한다.

---

## Task 6: findings §9 갱신 + INGEST + TODO

**Files:** Modify `docs/01_eda_findings.md`, `wiki/data-profile/eda-findings.md`, `wiki/models/model-decisions.md`, `TODO.md`, `TODO_ARCHIVE.md`

- [ ] **Step 1: findings에 §9 "Day-level 장소추정 캡션 보강" 추가**

`docs/01_eda_findings.md` 끝에 §9 추가: ① §1 스모크 결과(multi-image 직접/montage) ② 그룹수·day-place 추정 예시 ③ **비교군 3 recall(@5/@10·MRR)** + **지명질의(제주·일산) 보강폭**(0.00→?) ④ **공격 vs 보수 환각율·정확도** ⑤ 권고(보강 채택 여부·강도). 실측 wall-clock 포함. macOS NFD→NFC 교정 메모.

- [ ] **Step 2: wiki INGEST (AGENTS.md 프로토콜)**

`wiki/data-profile/eda-findings.md`에 day-place 보강 수치 1~2줄 추가 + `wiki/models/model-decisions.md` 캡션 행에 "지명 보강: gemma4:26b day-place" status 한 줄. frontmatter `last_verified: 2026-06-04`, `status: fresh`.

- [ ] **Step 3: TODO 갱신**

`TODO.md` "다음 세션 후보"의 D20 image leg 항목은 **유지**(이번은 캡션 경로). 신규 완료 항목(day-place 보강 EDA)을 `TODO_ARCHIVE.md`로 이관(완료 시각 분단위 + commit hash, AGENTS.md §7). 결과에 따라 "지명 보강 v1 채택 결정"을 ADR flag로 TODO에 추가(결정은 사용자).

- [ ] **Step 4: Commit**

```bash
git add docs/01_eda_findings.md wiki/data-profile/eda-findings.md wiki/models/model-decisions.md TODO.md TODO_ARCHIVE.md
git commit -m "docs: day-level 장소추정 캡션 보강 EDA 결과 — 지명 recall 보강폭·환각 trade-off (04 notebook)"
```

Run: 커밋. Expected: findings·wiki·TODO 갱신 보존(노트북·캐시는 gitignore).

---

## Self-Review (작성자 점검)

- **Spec coverage**: spec §0→T1, §1 스모크→T2, §2 그룹핑·추정→T3, §3 결합·임베딩→T4, §4 평가(recall+정확도+환각율)→T5, §6 산출물→T6. 프롬프트 A/B(spec §9)→T3S3, 평가법(spec §10)→T5, 정답누출 차단(spec §3)→T3S3 주석. 비범위(image leg·모델 A/B)는 plan 미포함(정상). ✓
- **Placeholder scan**: `MULTI_IMAGE_OK`·`QUERIES`·`PLACE_ALIAS`는 **의도적 개입점/조정점**(주석 명시)이지 빈칸 아님. 모든 코드 step은 실제 코드 포함. ✓
- **Type consistency**: `montage(paths,cols,cell)`·`day_groups(df)`·`rep_sample(g,n)`·`estimate_place(paths,prompt,multi_ok)`·`combine(scene,place)`·`embed(text)`·`recall_mrr(q,P,labels,gold,ks)` 시그니처가 정의 후 동일 사용. 캐시 파일명(`day_places_04`·`pool_embeddings_04`)·컬럼(`group_key`·`aggressive`·`conservative`·`text_base/aggr/cons`)·arm 키 T3~T5 일관. `_sort` 컬럼은 day_groups가 생성→rep_sample이 사용(일관). ✓
- **재사용 정합**: 03 자산(`pool_captions_03.parquet`·`recall_mrr`·`embed`·QUERIES·평가풀)을 승계해 03 숫자와 직접 비교 가능. ✓
