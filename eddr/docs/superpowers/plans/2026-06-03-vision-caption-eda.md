# Vision 캡션 프롬프트 EDA — 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development 또는 superpowers:executing-plans로 task별 구현. 단, 본 계획은 **EDA 노트북**이라 §2 정성 평가는 사람이 표를 보고 판단한다(자동 완주 불가) — Task 3 종료 후 사용자 개입점이 있다.

**Goal:** 02 핸드오프(manifest+썸네일)를 입력으로, 로컬 Ollama 캡션 3종 프롬프트를 정성→정량 2단계로 비교해 best 프롬프트와 D19 판정을 findings에 남긴다.

**Architecture:** `notebooks/03_vision_caption_eda.ipynb`(gitignore) 단일 노트북. §0 셋업 → §1 선행 픽셀파악 → §2 정성(24장×3프롬프트×2모델) → §3 정량(질의셋→캡션 임베딩 recall) → §4 findings 갱신. 캡션·임베딩은 parquet 캐시로 재실행 저렴.

**Tech Stack:** Jupyter, pandas/pyarrow, Pillow(+pillow-heif), numpy, `ollama` 0.6.2 python client, 로컬 Ollama 서버(`gemma4:e2b`/`gemma4:26b`/`qwen3-embedding:8b`).

**검증 전략(EDA 완화):** pytest 스위트 대신 **노트북 inline `assert`(순수 함수) + 셀 실행–관찰(시각화·캡션·정성)**. 순수 로직(픽셀 지표·recall@k·질의 정규화)만 합성 입력 assert로 잠근다. 근거: EDA는 구현 게이트가 아닌 insight(프로젝트 규약), 정성은 사람 판단.

---

## File Structure

- **Create**: `notebooks/03_vision_caption_eda.ipynb` — 본 EDA 노트북 (gitignore)
- **Read**: `data/eda_cache/vision_manifest.parquet`(1,737행), `data/eda_cache/thumbs/<폴더>/*.jpg`
- **Create(캐시)**: `data/eda_cache/pixel_metrics_03.parquet`, `data/eda_cache/captions_03.parquet`, `data/eda_cache/pool_embeddings_03.parquet`
- **Modify**: `docs/01_eda_findings.md`(Vision 캡션 EDA 섹션 추가), `wiki/data-profile/eda-findings.md`, `wiki/models/model-decisions.md`, `TODO.md`, `TODO_ARCHIVE.md`

> 노트북 셀은 `NotebookEdit`로 추가한다. 아래 각 Task의 "Cell" = 노트북에 추가할 셀 1개.

---

## Task 1: §0 셋업 — imports·Ollama 연결·manifest 로드

**Files:** Create `notebooks/03_vision_caption_eda.ipynb`

- [ ] **Step 1: 마크다운 헤더 셀**

```markdown
# 03 — Vision 캡션 프롬프트 EDA
spec: docs/superpowers/specs/2026-06-03-vision-caption-eda-design.md
입력: 02 핸드오프(vision_manifest.parquet + thumbs/). 전부 로컬 Ollama, 외부 전송 0(ADR-0001).
```

- [ ] **Step 2: 셋업 코드 셀 — imports·경로·seed**

```python
import json, time, random
from pathlib import Path
import numpy as np
import pandas as pd
from PIL import Image, ImageFilter
import pillow_heif; pillow_heif.register_heif_opener()
import ollama

SEED = 42
random.seed(SEED); np.random.seed(SEED)

ROOT = Path.cwd().parent if Path.cwd().name == "notebooks" else Path.cwd()
CACHE = ROOT / "data" / "eda_cache"
MANIFEST = CACHE / "vision_manifest.parquet"
THUMB_DIR = CACHE / "thumbs"

CAP_MODELS = ["gemma4:e2b", "gemma4:26b"]
EMB_MODEL = "qwen3-embedding:8b"
```

- [ ] **Step 3: Ollama 연결·모델 존재 확인 셀**

```python
installed = {m.model for m in ollama.list().models}
need = set(CAP_MODELS) | {EMB_MODEL}
missing = need - installed
assert not missing, f"누락 모델: {missing} — ollama pull 필요"
print("Ollama OK:", sorted(need))
```

Run: 셀 실행. Expected: `Ollama OK: ['gemma4:26b', 'gemma4:e2b', 'qwen3-embedding:8b']`, assert 통과.

- [ ] **Step 4: manifest 로드·sanity 셀**

```python
m = pd.read_parquet(MANIFEST)
assert len(m) == 1737, len(m)
assert m["thumb_path"].notna().all()
m["ext"] = m["local_path"].str.lower().str.rsplit(".", n=1).str[-1]
print(len(m), "행 · bucket:", m["bucket"].value_counts().to_dict())
```

Run: 셀 실행. Expected: `1737 행 · bucket: {'icloud_new': 1310, 'overlap': 427}`.

- [ ] **Step 5: Commit (노트북은 gitignore라 .gitignore만 확인)**

```bash
git status --short notebooks/  # 03 노트북이 무시되는지 확인(추적 안 됨이 정상)
# 노트북 자체는 커밋하지 않음(ADR-0001). 진행 기록은 findings/plan에 남긴다.
```

---

## Task 2: §1 선행 픽셀 파악 — manifest 재집계 + 썸네일 픽셀 지표

**Files:** Modify `notebooks/03_vision_caption_eda.ipynb`; Create `data/eda_cache/pixel_metrics_03.parquet`

- [ ] **Step 1: 픽셀 지표 순수 함수 셀**

```python
def pixel_metrics(thumb_path: str) -> dict:
    """썸네일에서 저비용 지표: 밝기·노출클리핑·흐림·종횡비."""
    im = Image.open(thumb_path).convert("L")
    a = np.asarray(im, dtype=np.float32)
    lap = np.asarray(im.filter(ImageFilter.FIND_EDGES), dtype=np.float32)
    h, w = a.shape
    return {
        "brightness": float(a.mean()),                     # 0(검정)~255(흰색)
        "clip_lo": float((a < 8).mean()),                  # 암부 클리핑 비율
        "clip_hi": float((a > 247).mean()),                # 명부 클리핑 비율
        "blur": float(lap.var()),                          # 낮을수록 흐림
        "aspect": float(w / h),
    }
```

- [ ] **Step 2: 순수 함수 inline assert 셀(합성 이미지)**

```python
def _synth(val):
    p = CACHE / f"_synth_{val}.jpg"; Image.new("L", (64, 48), val).save(p); return str(p)

mb_black = pixel_metrics(_synth(0)); mb_white = pixel_metrics(_synth(255))
assert mb_black["brightness"] < 1 and mb_white["brightness"] > 254
assert mb_black["clip_lo"] == 1.0 and mb_white["clip_hi"] == 1.0
assert abs(mb_black["aspect"] - 64/48) < 1e-6
print("pixel_metrics assert OK")
for v in (0, 255): (CACHE / f"_synth_{v}.jpg").unlink()
```

Run: 셀 실행. Expected: `pixel_metrics assert OK`.

- [ ] **Step 3: 전수 픽셀 지표 계산 + 캐시 셀**

```python
PIX = CACHE / "pixel_metrics_03.parquet"
if PIX.exists():
    px = pd.read_parquet(PIX)
else:
    rows, fails = [], []
    t0 = time.time()
    for tp in m["thumb_path"]:
        try: rows.append({"thumb_path": tp, **pixel_metrics(tp)})
        except Exception as e: fails.append((tp, str(e)))
    px = pd.DataFrame(rows); px.to_parquet(PIX)
    print(f"{len(px)} 지표 · 실패 {len(fails)} · {time.time()-t0:.0f}s")
mx = m.merge(px, on="thumb_path", how="left")
assert mx["brightness"].notna().mean() > 0.99
```

Run: 셀 실행. Expected: ~1737 지표, 실패 0~소수, brightness 99%+ 존재.

- [ ] **Step 4: manifest 재집계 + png/jpg 화질 비교 출력 셀**

```python
print("== folder_top top10 =="); print(m["folder_top"].value_counts().head(10))
print("== 포맷 ==", m["ext"].value_counts().to_dict())
print("== match_confidence ==", m["match_confidence"].value_counts().to_dict())
print("== 해상도 MP 분위 =="); print((mx.width*mx.height/1e6).describe(percentiles=[.1,.5,.9]))
print("== png vs jpg 밝기/흐림 중앙값 ==")
print(mx.groupby("ext")[["brightness","blur","clip_lo","clip_hi"]].median())
```

Run: 셀 실행. Expected: 포맷·밝기·흐림 분포 출력. png 집단의 픽셀 특성이 jpg와 구분되는지 관찰.

- [ ] **Step 5: "어려운 축" 식별 셀**

```python
mx["hard"] = (mx["brightness"] < 40) | (mx["clip_lo"] > 0.5) | (mx["blur"] < mx["blur"].quantile(0.1))
print("어려운 후보(저조도/암부클리핑/흐림 하위10%):", int(mx["hard"].sum()))
```

Run: 셀 실행. Expected: 어려운 후보 N장 표시 → Task 3 샘플 층화에 사용.

---

## Task 3: §2 정성 캡션 비교 — 24장 × 3프롬프트 × 2모델

**Files:** Modify `notebooks/03_vision_caption_eda.ipynb`; Create `data/eda_cache/captions_03.parquet`

- [ ] **Step 1: 프롬프트 3종 상수 셀(영어 출력 고정)**

```python
PROMPTS = {
  "P1_concise": "Describe this photo in one concise English sentence.",
  "P2_struct": ("Describe this photo in English. Cover: place/setting type, "
      "main objects or subjects, activity or event, any visible text, overall mood. "
      "Be specific and factual; do not guess the names of people."),
  "P3_hybrid": ("Describe this photo in English in 1-2 sentences, then list 5-10 "
      "searchable keywords (nouns: places, objects, events, food, activities).\n"
      "Format:\nCaption: <sentence>\nKeywords: <comma-separated>"),
}
```

- [ ] **Step 2: 층화 샘플 24장 선정 함수 + assert 셀**

```python
def stratified_sample(df, n=24, seed=SEED):
    """folder_top·bucket·포맷·밝기·hard 다양성 커버. 결정적."""
    df = df.copy()
    df["bright_band"] = pd.cut(df["brightness"], [0,60,120,256], labels=["dark","mid","bright"])
    strata = df.groupby(["bucket","ext","bright_band"], observed=True)
    picks = strata.sample(1, random_state=seed)        # 각 층 1장
    extra = df[df["hard"]].sample(min(4, df["hard"].sum()), random_state=seed)  # 어려운 축 보강
    out = pd.concat([picks, extra]).drop_duplicates("thumb_path").head(n)
    if len(out) < n:                                    # 부족분 무작위 채움
        rest = df[~df["thumb_path"].isin(out["thumb_path"])].sample(n-len(out), random_state=seed)
        out = pd.concat([out, rest])
    return out.head(n).reset_index(drop=True)

samp = stratified_sample(mx)
assert len(samp) == 24
assert samp["folder_top"].nunique() >= 6 and samp["ext"].nunique() >= 2
print("샘플 24 OK · folders:", samp["folder_top"].nunique(), "· png:", (samp.ext=="png").sum())
```

Run: 셀 실행. Expected: `샘플 24 OK`, folder 6+ / png 1+ 포함.

- [ ] **Step 3: Ollama 캡션 함수 셀(flag-skip)**

```python
def caption(thumb_path, model, prompt):
    try:
        r = ollama.chat(model=model, messages=[
            {"role":"user","content":prompt,"images":[thumb_path]}], options={"seed":SEED})
        return r["message"]["content"].strip()
    except Exception as e:
        return f"__ERR__:{e}"
```

- [ ] **Step 4: 144 캡션 생성 + 캐시 셀**

```python
CAPS = CACHE / "captions_03.parquet"
if CAPS.exists():
    caps = pd.read_parquet(CAPS)
else:
    recs, t0 = [], time.time()
    for _, row in samp.iterrows():
        for model in CAP_MODELS:
            for pid, ptext in PROMPTS.items():
                recs.append({"thumb_path":row.thumb_path,"folder_top":row.folder_top,
                    "model":model,"prompt_id":pid,"caption":caption(row.thumb_path,model,ptext)})
    caps = pd.DataFrame(recs); caps.to_parquet(CAPS)
    print(f"{len(caps)} 캡션 · {time.time()-t0:.0f}s · 에러 {caps.caption.str.startswith('__ERR__').sum()}")
assert len(caps) == 24*2*3
```

Run: 셀 실행(시간 소요 — 26b 72회). Expected: 144 캡션, 에러 0~소수, 시간 보고.

- [ ] **Step 5: 정성 비교 표 출력 셀(썸네일 + 6캡션)**

```python
from IPython.display import display, HTML
def show_row(thumb):
    sub = caps[caps.thumb_path==thumb]
    html = f'<img src="{thumb}" width="240"><table>'
    for model in CAP_MODELS:
        for pid in PROMPTS:
            c = sub[(sub.model==model)&(sub.prompt_id==pid)].caption.iloc[0]
            html += f"<tr><td><b>{model}/{pid}</b></td><td>{c}</td></tr>"
    display(HTML(html+"</table>"))
for thumb in samp.thumb_path.head(24): show_row(thumb)
```

Run: 셀 실행. Expected: 24장 각각 썸네일 + 6캡션 표 렌더.

- [ ] **Step 6: 정성 평가 메모 마크다운 셀(사람이 작성)**

```markdown
## §2 정성 평가 (사람 판단)
각 프롬프트·모델을 [장소/객체/이벤트 포착 · 환각 · 검색어휘 포함]로 체크.
- P1_concise: ...
- P2_struct: ...
- P3_hybrid: ...
**→ 정량으로 넘길 후보 1~2 조합(model/prompt_id): _____**
```

> ⚠️ **사용자 개입점**: 이 셀의 표를 보고 best 1~2 조합을 직접 적는다. Task 4가 그 값을 입력으로 쓴다.

---

## Task 4: §3 정량 검색 recall + D19 판정

**Files:** Modify `notebooks/03_vision_caption_eda.ipynb`; Create `data/eda_cache/pool_embeddings_03.parquet`

- [ ] **Step 1: 한국어 질의셋(자동초안) 셀 — 사용자 보강**

```python
# 자동초안: folder_top → 한국어 질의 (대표 폴더만; 사용자가 추가/수정)
QUERIES = {
  "결혼식 사진": "wedding",
  "아이슬란드 여행": "2022_아이슬란드",
  "제주도에서 찍은 사진": "200620_23_제주",
  "이탈리아 여행": "2019_이탈리아",
  "벚꽃 사진": "2019_벚꽃",
  "부산에서": "181229_30_busan",
  "강릉 바다": "190216_17_강릉",
  # TODO(사용자): 본인이 실제 물어볼 한국어 질의 2~5개 추가, 정답 folder_top 매핑
}
assert all(v in set(m.folder_top) for v in QUERIES.values()), \
    [v for v in QUERIES.values() if v not in set(m.folder_top)]
assert 7 <= len(QUERIES) <= 20
print(len(QUERIES), "질의 · 정답 폴더 검증 OK")
```

Run: 셀 실행. Expected: 질의 7~20개, 정답 폴더가 manifest에 모두 존재(assert 통과). 폴더명 불일치 시 assert가 잡아줌.

- [ ] **Step 2: 평가 풀 ~400장 선정 셀**

```python
gold_folders = set(QUERIES.values())
pos = m[m.folder_top.isin(gold_folders)]                       # 정답 폴더 전부
neg = m[~m.folder_top.isin(gold_folders)].sample(
    min(400-len(pos), (~m.folder_top.isin(gold_folders)).sum()), random_state=SEED)  # 디스트랙터
pool = pd.concat([pos, neg]).drop_duplicates("thumb_path").reset_index(drop=True)
print("풀:", len(pool), "· 정답군:", len(pos), "· 디스트랙터:", len(neg))
```

Run: 셀 실행. Expected: 풀 ~400, 정답군+디스트랙터 구성.

- [ ] **Step 3: best 프롬프트 지정 + 풀 캡션 생성·캐시 셀**

```python
BEST = [("gemma4:e2b","P2_struct")]   # ← Task 3 정성 결과로 사용자가 교체(1~2개)
POOLCAP = CACHE / "pool_captions_03.parquet"
if POOLCAP.exists():
    pc = pd.read_parquet(POOLCAP)
else:
    recs, t0 = [], time.time()
    for _, row in pool.iterrows():
        for model, pid in BEST:
            recs.append({"thumb_path":row.thumb_path,"folder_top":row.folder_top,
                "model":model,"prompt_id":pid,"caption":caption(row.thumb_path,model,PROMPTS[pid])})
    pc = pd.DataFrame(recs); pc.to_parquet(POOLCAP)
    print(f"{len(pc)} 풀 캡션 · {time.time()-t0:.0f}s")
```

Run: 셀 실행(e2b 위주 ~400회). Expected: 풀 캡션 생성, 시간 보고.

- [ ] **Step 4: 임베딩 함수 + recall@k 순수 함수 + assert 셀**

```python
def embed(text):
    return np.asarray(ollama.embed(model=EMB_MODEL, input=text).embeddings[0], dtype=np.float32)

def recall_mrr(q_emb, pool_embs, pool_labels, gold, ks=(5,10)):
    sims = pool_embs @ q_emb / (np.linalg.norm(pool_embs,axis=1)*np.linalg.norm(q_emb)+1e-9)
    order = np.argsort(-sims)
    hits = [i for i,idx in enumerate(order) if pool_labels[idx]==gold]
    rr = 1.0/(hits[0]+1) if hits else 0.0
    return {f"recall@{k}": float(any(h < k for h in hits)) for k in ks} | {"mrr": rr}

# 합성 assert: 정답이 1위면 recall@5=1, mrr=1
_pe = np.array([[1,0],[0,1],[0.9,0.1]], dtype=np.float32)
_r = recall_mrr(np.array([1,0],dtype=np.float32), _pe, ["g","x","g"], "g")
assert _r["recall@5"]==1.0 and abs(_r["mrr"]-1.0)<1e-6, _r
print("recall_mrr assert OK")
```

Run: 셀 실행. Expected: `recall_mrr assert OK`.

- [ ] **Step 5: 풀 임베딩 생성·캐시 + 질의별 recall 셀**

```python
POOLEMB = CACHE / "pool_embeddings_03.parquet"
if POOLEMB.exists():
    emb_df = pd.read_parquet(POOLEMB)
else:
    pc2 = pc.copy()
    pc2["emb"] = [embed(c).tolist() for c in pc2.caption]
    emb_df = pc2; emb_df.to_parquet(POOLEMB)
results = []
for (model,pid), g in emb_df.groupby(["model","prompt_id"]):
    P = np.array(g.emb.tolist(), dtype=np.float32); labels = g.folder_top.tolist()
    for q, gold in QUERIES.items():
        results.append({"model":model,"prompt_id":pid,"query":q,**recall_mrr(embed(q),P,labels,gold)})
res = pd.DataFrame(results)
```

Run: 셀 실행. Expected: 질의×조합별 recall 레코드.

- [ ] **Step 6: 프롬프트 비교표 + D19 판정 셀**

```python
print("== 프롬프트/모델별 평균 ==")
print(res.groupby(["model","prompt_id"])[["recall@5","recall@10","mrr"]].mean().round(3))
print("\n== 질의별 recall@10 (best 조합) ==")
print(res.pivot_table(index="query", columns=["model","prompt_id"], values="recall@10"))
mean_r10 = res.groupby(["model","prompt_id"])["recall@10"].mean().max()
print(f"\nD19 판정: 최고 recall@10 = {mean_r10:.2f} → "
      f"{'PASS(한국어↔영어캡션 매칭 작동)' if mean_r10>=0.5 else '관찰(보강 필요)'}")
```

Run: 셀 실행. Expected: 비교표 + D19 PASS/관찰. **절대 임계는 참고용**(weak label 한계) — 프롬프트 상대순위가 결론.

---

## Task 5: §4 findings 갱신 + INGEST + TODO

**Files:** Modify `docs/01_eda_findings.md`, `wiki/data-profile/eda-findings.md`, `wiki/models/model-decisions.md`, `TODO.md`, `TODO_ARCHIVE.md`

- [ ] **Step 1: findings에 "Vision 캡션 EDA" 섹션 추가**

`docs/01_eda_findings.md` 끝에 §8 추가: 선행파악 요약(png/jpg 화질차·어려운 축) · 정성 결과표(프롬프트·모델 강약점) · recall 비교(@5/@10·MRR) · **best 프롬프트 전문** · **D19 판정**(PASS/관찰) · 모델 비교(e2b vs 26b). 실측 wall-clock 포함.

- [ ] **Step 2: wiki INGEST (AGENTS.md 프로토콜)**

`wiki/data-profile/eda-findings.md`에 캡션 EDA 수치 1~2줄 + `wiki/models/model-decisions.md`의 캡션 행 status를 `pending → (정성/recall 근거 기록)`으로 갱신. frontmatter `last_verified: 2026-06-03`.

- [ ] **Step 3: TODO 갱신**

`TODO.md`의 "D19/D20 Vision bridge 검증" 항목을 완료 처리 → `TODO_ARCHIVE.md`로 이관(완료 시각 분단위 + commit hash, AGENTS.md §7). best 프롬프트·D19 결과를 한 줄 요약. 후속(image-embedding leg, Qwen3-VL A/B)이 남으면 TODO에 신규 항목.

- [ ] **Step 4: Commit**

```bash
git add docs/01_eda_findings.md wiki/data-profile/eda-findings.md wiki/models/model-decisions.md TODO.md TODO_ARCHIVE.md
git commit -m "docs: vision 캡션 EDA 결과 — best 프롬프트·D19 판정·모델 비교 (03 notebook)"
```

Run: 커밋. Expected: findings·wiki·TODO 갱신 보존(노트북·캐시는 gitignore).

---

## Self-Review (작성자 점검)

- **Spec coverage**: §0→T1, §1→T2, §2→T3, §3→T4, §4/산출물→T5, 프롬프트 3종(spec §9)→T3S1, 평가(spec §10)→T3S6·T4S6. 비범위(Qwen3-VL·image-embedding)는 plan에 미포함(정상). ✓
- **Placeholder scan**: `BEST`/`QUERIES`의 사용자 입력은 **의도적 개입점**(주석 명시)이지 빈칸 아님. 코드 step은 실제 코드 포함. ✓
- **Type consistency**: `caption(thumb,model,prompt)`·`pixel_metrics`·`recall_mrr`·`embed` 시그니처가 정의 후 동일하게 사용. 캐시 파일명 T2/T3/T4 일관. ✓
