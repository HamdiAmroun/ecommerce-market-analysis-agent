# Manual Testing Guide

This document covers every meaningful execution path in the system with exact API payloads, expected field values, and what each test is designed to verify.

**Prerequisites:** Service running locally.

```bash
# Option A — Docker (recommended)
docker-compose up --build

# Option B — Local Python
uvicorn app.main:app --reload --port 8000
```

All `curl` commands target `http://localhost:8000`.

> **Windows note:** Replace single quotes with double quotes and escape inner quotes.
> ```powershell
> # PowerShell equivalent
> Invoke-RestMethod -Uri http://localhost:8000/health
> Invoke-RestMethod -Uri http://localhost:8000/analyze -Method Post `
>   -ContentType "application/json" `
>   -Body '{"product_name":"iPhone 16 Pro","category":"consumer electronics"}'
> ```

---

## Table of Contents

1. [Health Check](#1-health-check)
2. [Known Product — Standard Depth](#2-known-product--standard-depth-iphone-16-pro)
3. [Unknown Product — Dynamic Sentiment Skip](#3-unknown-product--dynamic-sentiment-skip)
4. [Quick Depth — Reduced Pipeline](#4-quick-depth--reduced-pipeline)
5. [Deep Mode — Fallback (No LLM Key)](#5-deep-mode--fallback-no-llm-key)
6. [Deep Mode — LLM Path (With API Key)](#6-deep-mode--llm-path-with-api-key)
7. [Cross-Tool Influence — Budget Product](#7-cross-tool-influence--budget-product)
8. [Invalid Request — Validation Error](#8-invalid-request--validation-error)
9. [Non-Existent Job — 404](#9-non-existent-job--404)
10. [List All Jobs](#10-list-all-jobs)
11. [Full End-to-End Flow Script](#11-full-end-to-end-flow-script)

---

## 1. Health Check

**Purpose:** Confirm the service is up and shows correct LLM availability.

```bash
curl http://localhost:8000/health
```

**Expected status:** `200 OK`

**Expected response (no API key):**
```json
{
  "status": "ok",
  "version": "1.0.0",
  "llm_available": false,
  "llm_model": "llama-3.3-70b-versatile"
}
```

**Expected response (with `GROQ_API_KEY` set):**
```json
{
  "status": "ok",
  "version": "1.0.0",
  "llm_available": true,
  "llm_model": "llama-3.3-70b-versatile"
}
```

**What to verify:**
- `status` is always `"ok"`
- `llm_available` flips correctly based on whether `GROQ_API_KEY` is set in the environment

---

## 2. Known Product — Standard Depth (iPhone 16 Pro)

**Purpose:** Happy path. Catalog product runs all 3 tools, sentiment is NOT skipped, report is generated.

### Step 1 — Submit

```bash
curl -s -X POST http://localhost:8000/analyze \
  -H "Content-Type: application/json" \
  -d '{
    "product_name": "iPhone 16 Pro",
    "category": "consumer electronics",
    "target_market": "US market",
    "analysis_depth": "standard"
  }'
```

**Expected status:** `202 Accepted`

**Expected response:**
```json
{
  "job_id": "<uuid>",
  "status": "pending",
  "product_name": "iPhone 16 Pro",
  "category": "consumer electronics",
  "target_market": "US market",
  "analysis_depth": "standard",
  "created_at": "<datetime>",
  "completed_at": null,
  "report": null,
  "error": null
}
```

### Step 2 — Poll (replace `<job_id>` with value from Step 1)

```bash
curl -s http://localhost:8000/analyze/<job_id> | python -m json.tool
```

**Expected status:** `200 OK`

**Key fields to verify:**

| Field | Expected value | Why |
|-------|----------------|-----|
| `status` | `"completed"` | Both required tools succeeded |
| `report.generated_by` | `"fallback"` (no key) / `"llm"` (with key) | LLM path depends on env |
| `report.product_analysis.average_price` | `1019.25` | (999.99+999+979+1099) / 4 |
| `report.product_analysis.price_range_min` | `979.00` | eBay cheapest |
| `report.product_analysis.price_range_max` | `1099.00` | Apple Store |
| `report.product_analysis.market_position` | `"premium"` | Hand-crafted catalog value |
| `report.product_analysis.competitor_count` | `3` | Samsung, Pixel, OnePlus |
| `report.sentiment_analysis` | **not null** | Catalog product → sentiment NOT skipped |
| `report.market_trends.trend_direction` | `"stable"` | Consumer electronics category default |
| `report.deep_analysis` | `null` | Standard mode, no deep section |
| `report.metadata.tools_succeeded` | `3` | All 3 ran and succeeded |
| `report.metadata.tools_skipped` | `0` | Known product → no skip |
| `report.metadata.warnings` | `[]` | No issues |

**Sample product_analysis block:**
```json
"product_analysis": {
  "average_price": 1019.25,
  "price_range_min": 979.0,
  "price_range_max": 1099.0,
  "market_position": "premium",
  "competitor_count": 3,
  "top_platforms": [
    {"platform": "Amazon", "price": 999.99, "currency": "USD"},
    {"platform": "Best Buy", "price": 999.0, "currency": "USD"},
    {"platform": "eBay (new)", "price": 979.0, "currency": "USD"},
    {"platform": "Apple Store", "price": 1099.0, "currency": "USD"}
  ],
  "top_competitors": [
    {"name": "Samsung Galaxy S25 Ultra", "price": 1299.99, "market_share_pct": 28.0},
    {"name": "Google Pixel 9 Pro", "price": 999.0, "market_share_pct": 8.0},
    {"name": "OnePlus 13", "price": 899.0, "market_share_pct": 3.5}
  ]
}
```

---

## 3. Unknown Product — Dynamic Sentiment Skip

**Purpose:** Verify the dynamic orchestration mechanism. An unknown product triggers `skip_if` — sentiment analysis is skipped at runtime, not failed.

### Step 1 — Submit

```bash
curl -s -X POST http://localhost:8000/analyze \
  -H "Content-Type: application/json" \
  -d '{
    "product_name": "XyloGadget Pro 3000",
    "category": "consumer electronics",
    "analysis_depth": "standard"
  }'
```

### Step 2 — Poll

```bash
curl -s http://localhost:8000/analyze/<job_id> | python -m json.tool
```

**Key fields to verify:**

| Field | Expected value | Why |
|-------|----------------|-----|
| `status` | `"completed"` | 2 required tools succeeded |
| `report.sentiment_analysis` | `null` | Sentiment was skipped, not run |
| `report.metadata.tools_succeeded` | `2` | Only product + trend ran successfully |
| `report.metadata.tools_skipped` | `1` | Sentiment skipped by skip_if |
| `report.metadata.tools_failed` | `0` | Nothing failed — skip ≠ failure |
| `report.metadata.warnings` | contains `"skipped"` | Warning message logged |
| `report.product_analysis.market_position` | `"mid-range"` | Generic category default for electronics |

**Why this matters:** The pipeline re-evaluated its own shape after `ProductCollector` returned `data_source: "generic"`. Running sentiment on a product with no real review base would produce category-average noise — the system correctly suppresses it and documents the gap in warnings.

**Sample metadata block:**
```json
"metadata": {
  "tool_execution_ms": {
    "product_collector": 101.4,
    "sentiment_analyzer": 0.0,
    "trend_analyzer": 122.8
  },
  "total_execution_ms": 234.2,
  "tools_succeeded": 2,
  "tools_failed": 0,
  "tools_skipped": 1,
  "warnings": [
    "Optional tool 'sentiment_analyzer' skipped: no catalog data found — sentiment omitted"
  ]
}
```

---

## 4. Quick Depth — Reduced Pipeline

**Purpose:** Verify `quick` mode runs only 2 tools and never attempts sentiment (not skipped — simply not in the pipeline).

### Step 1 — Submit

```bash
curl -s -X POST http://localhost:8000/analyze \
  -H "Content-Type: application/json" \
  -d '{
    "product_name": "Nike Air Max 270",
    "category": "athletic footwear",
    "analysis_depth": "quick"
  }'
```

### Step 2 — Poll

```bash
curl -s http://localhost:8000/analyze/<job_id> | python -m json.tool
```

**Key fields to verify:**

| Field | Expected value | Why |
|-------|----------------|-----|
| `status` | `"completed"` | Both tools succeeded |
| `report.sentiment_analysis` | `null` | Not in pipeline at all |
| `report.metadata.tools_succeeded` | `2` | Product + trend only |
| `report.metadata.tools_skipped` | `0` | Quick mode doesn't even attempt sentiment — different from skip_if |
| `report.product_analysis.market_position` | `"mid-range"` | Nike Air Max 270 catalog value |
| `report.product_analysis.average_price` | `142.25` | (150+139.99+150+129) / 4 |
| `report.market_trends.trend_direction` | `"rising"` | Athletic footwear category default |

**Distinction from Test 3:** In Test 3 the sentiment step was attempted and then skipped by a runtime condition (`tools_skipped: 1`). Here it was never in the pipeline — `tools_skipped: 0`. Two different mechanisms producing the same report-level result (`sentiment_analysis: null`), for different reasons.

---

## 5. Deep Mode — Fallback (No LLM Key)

**Purpose:** Verify `deep` mode produces a `deep_analysis` section via the deterministic fallback when no API key is set.

### Step 1 — Submit

```bash
curl -s -X POST http://localhost:8000/analyze \
  -H "Content-Type: application/json" \
  -d '{
    "product_name": "MacBook Pro 14",
    "category": "consumer electronics",
    "target_market": "US market",
    "analysis_depth": "deep"
  }'
```

### Step 2 — Poll

```bash
curl -s http://localhost:8000/analyze/<job_id> | python -m json.tool
```

**Key fields to verify:**

| Field | Expected value | Why |
|-------|----------------|-----|
| `status` | `"completed"` | All 3 tools succeeded |
| `report.generated_by` | `"fallback"` | No API key set |
| `report.deep_analysis` | **not null** | Deep mode always populates this section |
| `report.deep_analysis.key_risks` | list of 1–3 strings | Heuristic risks grounded in product data |
| `report.deep_analysis.market_opportunities` | list of 1–3 strings | Heuristic opportunities |
| `report.deep_analysis.enriched_recommendations` | list with priority + rationale | Each item has `text`, `priority`, `rationale` |
| `report.metadata.tools_skipped` | `0` | MacBook Pro 14 is in catalog |

**Expected `deep_analysis` structure:**
```json
"deep_analysis": {
  "key_risks": [
    "Price competition from Dell XPS 15 ($1799.99) could erode market share if value perception weakens.",
    "Persistent negative sentiment around '<top_neg_theme>' may suppress repeat purchase rate if unaddressed."
  ],
  "market_opportunities": [
    "Strong momentum in the premium segment supports a limited-edition variant strategy to test price ceiling and drive PR coverage."
  ],
  "enriched_recommendations": [
    {
      "text": "Resolve top complaint '<theme>' via product update or messaging fix.",
      "priority": "high",
      "rationale": "'<theme>' is the highest-frequency negative theme — directly impacts conversion and repeat purchase."
    },
    {
      "text": "Reinforce value vs. Dell XPS 15 through bundled offers or warranty extension.",
      "priority": "high",
      "rationale": "Price gap vs. cheapest competitor ($1799.99) is the primary switching incentive — reducing it perceptually protects margin."
    },
    {
      "text": "Audit and optimise product listings across all top platforms.",
      "priority": "low",
      "rationale": "Platform listing quality directly affects organic ranking and conversion rate independent of market conditions."
    }
  ]
}
```

---

## 6. Deep Mode — LLM Path (With API Key)

**Purpose:** Verify the two-pass LLM flow in deep mode: intermediate competitive signal extraction followed by full synthesis with richer schema.

**Prerequisite:** `GROQ_API_KEY` must be set.

```bash
# Set key for this session
export GROQ_API_KEY=gsk_...
docker-compose up --build   # or restart uvicorn
```

### Step 1 — Confirm LLM is available

```bash
curl http://localhost:8000/health
# "llm_available": true  ← must see this before proceeding
```

### Step 2 — Submit

```bash
curl -s -X POST http://localhost:8000/analyze \
  -H "Content-Type: application/json" \
  -d '{
    "product_name": "Sony WH-1000XM5",
    "category": "consumer electronics",
    "target_market": "global",
    "analysis_depth": "deep"
  }'
```

### Step 3 — Poll

```bash
curl -s http://localhost:8000/analyze/<job_id> | python -m json.tool
```

**Key fields to verify:**

| Field | Expected value | Why |
|-------|----------------|-----|
| `report.generated_by` | `"llm"` | API key set, both LLM calls succeeded |
| `report.deep_analysis` | **not null** | LLM returned deep_analysis block |
| `report.deep_analysis.enriched_recommendations[*].priority` | `"high"` / `"medium"` / `"low"` | LLM assigned priorities per item |
| `report.deep_analysis.enriched_recommendations[*].rationale` | non-empty string | LLM cited specific data points |
| `report.executive_summary` | rich narrative, ≤ 120 words | LLM-authored, references pricing + sentiment + trends |
| `report.confidence_score` | `0.80`–`0.95` range | 3 tools succeeded → LLM uses upper band |
| `report.product_analysis.average_price` | `357.0` | (349.99+349.99+399.99+329) / 4 — always from tool, never LLM |

**What to look for:** The `executive_summary` and `recommendations` in LLM mode should directly reference specific numbers from the tool data (e.g. competitor prices, sentiment score, trend direction). If they are generic statements without data references, that's a quality issue worth noting.

---

## 7. Cross-Tool Influence — Budget Product

**Purpose:** Verify that `SentimentAnalyzer` adjusts its score range based on `market_position` from `ProductCollector`. A budget product should score more leniently than a premium one in the same category.

### Submit budget product

```bash
curl -s -X POST http://localhost:8000/analyze \
  -H "Content-Type: application/json" \
  -d '{
    "product_name": "Budget Earbuds X1",
    "category": "consumer electronics",
    "analysis_depth": "standard"
  }'
```

> Note: This is an unknown product → `data_source: "generic"` → **sentiment will be skipped** due to the skip_if condition. This is actually the correct behavior — unknown budget products have no review data. To test the cross-tool score adjustment directly, use a catalog product.

### Alternative — compare sentiment scores for catalog products

Submit two requests and compare their `sentiment_analysis.overall_score`:

```bash
# Premium product (score range shifted DOWN by 0.04-0.05)
curl -s -X POST http://localhost:8000/analyze \
  -H "Content-Type: application/json" \
  -d '{"product_name":"iPhone 16 Pro","category":"consumer electronics","analysis_depth":"standard"}'

# Mid-range product (standard score range, no adjustment)
curl -s -X POST http://localhost:8000/analyze \
  -H "Content-Type: application/json" \
  -d '{"product_name":"Nike Air Max 270","category":"athletic footwear","analysis_depth":"standard"}'
```

**What to observe:**
- Both return `sentiment_analysis.overall_score` — compare the ranges
- iPhone 16 Pro (premium) → score will be within `(0.30, 0.68)` adjusted range
- Nike Air Max 270 (mid-range, different category) → score within `(0.55, 0.88)`
- TrendAnalyzer for iPhone: `price_trend` values close to `1019.25` (actual average price from ProductCollector)
- TrendAnalyzer for Nike: `price_trend` values close to `142.25` (actual average price)

---

## 8. Invalid Request — Validation Error

**Purpose:** Confirm FastAPI model validation rejects malformed input with a structured error.

### Missing required field

```bash
curl -s -X POST http://localhost:8000/analyze \
  -H "Content-Type: application/json" \
  -d '{"category": "consumer electronics"}'
```

**Expected status:** `422 Unprocessable Entity`

**Expected response:**
```json
{
  "detail": [
    {
      "type": "missing",
      "loc": ["body", "product_name"],
      "msg": "Field required",
      "input": {"category": "consumer electronics"}
    }
  ]
}
```

### Invalid analysis_depth value

```bash
curl -s -X POST http://localhost:8000/analyze \
  -H "Content-Type: application/json" \
  -d '{"product_name": "iPhone 16 Pro", "category": "electronics", "analysis_depth": "ultra"}'
```

**Expected status:** `422 Unprocessable Entity`

**Expected response:** validation error on `analysis_depth` field, listing valid options.

### Empty body

```bash
curl -s -X POST http://localhost:8000/analyze \
  -H "Content-Type: application/json" \
  -d '{}'
```

**Expected status:** `422 Unprocessable Entity` — missing both `product_name` and `category`.

---

## 9. Non-Existent Job — 404

**Purpose:** Confirm the job store returns 404 for unknown job IDs rather than 500 or empty response.

```bash
curl -s http://localhost:8000/analyze/00000000-0000-0000-0000-000000000000
```

**Expected status:** `404 Not Found`

**Expected response:**
```json
{
  "detail": "Job 00000000-0000-0000-0000-000000000000 not found"
}
```

---

## 10. List All Jobs

**Purpose:** Verify the job list endpoint returns all submitted jobs in the current session.

```bash
curl -s http://localhost:8000/analyze | python -m json.tool
```

**Expected status:** `200 OK`

**Expected response:** array of `AnalysisResponse` objects for all jobs submitted since startup (in-memory store, cleared on restart).

```json
[
  {
    "job_id": "<uuid>",
    "status": "completed",
    "product_name": "iPhone 16 Pro",
    ...
  },
  {
    "job_id": "<uuid>",
    "status": "completed",
    "product_name": "XyloGadget Pro 3000",
    ...
  }
]
```

**What to verify:**
- All previously submitted jobs appear
- Jobs submitted before a service restart do not appear (confirms in-memory store, no persistence)
- Mix of `status: "completed"` jobs visible

---

## 11. Full End-to-End Flow Script

Paste this into a terminal to run all catalog products in sequence and poll each to completion.

```bash
BASE=http://localhost:8000

submit() {
  local name="$1" category="$2" depth="${3:-standard}"
  echo ""
  echo "=== Submitting: $name ($depth) ==="
  JOB=$(curl -s -X POST $BASE/analyze \
    -H "Content-Type: application/json" \
    -d "{\"product_name\":\"$name\",\"category\":\"$category\",\"analysis_depth\":\"$depth\"}" \
    | python -c "import sys,json; print(json.load(sys.stdin)['job_id'])")
  echo "job_id: $JOB"
  sleep 2
  echo "--- Result ---"
  curl -s $BASE/analyze/$JOB | python -c "
import sys, json
d = json.load(sys.stdin)
r = d.get('report', {}) or {}
m = r.get('metadata', {}) or {}
print(f\"  status        : {d['status']}\")
print(f\"  generated_by  : {r.get('generated_by','n/a')}\")
print(f\"  tools_succeeded: {m.get('tools_succeeded','n/a')}\")
print(f\"  tools_skipped : {m.get('tools_skipped','n/a')}\")
print(f\"  tools_failed  : {m.get('tools_failed','n/a')}\")
print(f\"  has_sentiment : {r.get('sentiment_analysis') is not None}\")
print(f\"  has_deep      : {r.get('deep_analysis') is not None}\")
print(f\"  confidence    : {r.get('confidence_score','n/a')}\")
print(f\"  warnings      : {m.get('warnings',[])}\")"
}

# 1 — Catalog product, standard
submit "iPhone 16 Pro" "consumer electronics" "standard"

# 2 — Unknown product, standard (expect sentiment skipped)
submit "XyloGadget Pro 3000" "consumer electronics" "standard"

# 3 — Catalog product, quick (expect sentiment null, not skipped)
submit "Nike Air Max 270" "athletic footwear" "quick"

# 4 — Catalog product, deep (expect deep_analysis present)
submit "MacBook Pro 14" "consumer electronics" "deep"

# 5 — Catalog product, another category
submit "Sony WH-1000XM5" "consumer electronics" "standard"

echo ""
echo "=== All jobs ==="
curl -s $BASE/analyze | python -c "
import sys, json
jobs = json.load(sys.stdin)
print(f'Total jobs in store: {len(jobs)}')
for j in jobs:
    print(f\"  {j['status']:10} | {j['product_name']:30} | depth={j['analysis_depth']}\")"
```

**Expected console output pattern:**
```
=== Submitting: iPhone 16 Pro (standard) ===
job_id: <uuid>
--- Result ---
  status        : completed
  generated_by  : fallback
  tools_succeeded: 3
  tools_skipped : 0
  tools_failed  : 0
  has_sentiment : True
  has_deep      : False
  confidence    : 0.85
  warnings      : []

=== Submitting: XyloGadget Pro 3000 (standard) ===
job_id: <uuid>
--- Result ---
  status        : completed
  generated_by  : fallback
  tools_succeeded: 2
  tools_skipped : 1
  tools_failed  : 0
  has_sentiment : False
  has_deep      : False
  confidence    : 0.567
  warnings      : ["Optional tool 'sentiment_analyzer' skipped: no catalog data found — sentiment omitted"]

=== Submitting: Nike Air Max 270 (quick) ===
job_id: <uuid>
--- Result ---
  status        : completed
  generated_by  : fallback
  tools_succeeded: 2
  tools_skipped : 0
  tools_failed  : 0
  has_sentiment : False
  has_deep      : False
  confidence    : 0.567
  warnings      : []

=== Submitting: MacBook Pro 14 (deep) ===
job_id: <uuid>
--- Result ---
  status        : completed
  generated_by  : fallback
  tools_succeeded: 3
  tools_skipped : 0
  tools_failed  : 0
  has_sentiment : True
  has_deep      : True
  confidence    : 0.85
  warnings      : []
```

---

## Quick Reference — Catalog Products

These are the five products with hand-crafted data (guaranteed to hit catalog path, sentiment will NOT be skipped):

| Product | Category | Market Position | Avg Price |
|---------|----------|-----------------|-----------|
| `iPhone 16 Pro` | consumer electronics | premium | $1019.25 |
| `iPhone 16` | consumer electronics | premium | $792.66 |
| `Nike Air Max 270` | athletic footwear | mid-range | $142.25 |
| `MacBook Pro 14` | consumer electronics | premium | $1982.66 |
| `Sony WH-1000XM5` | consumer electronics | premium | $357.24 |

Any other product name → `data_source: "generic"` → sentiment dynamically skipped in standard/deep mode.
