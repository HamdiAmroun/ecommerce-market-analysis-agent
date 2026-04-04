# E-Commerce Market Analysis Agent

A production-quality prototype demonstrating how a multi-tool AI agent can be designed to produce structured market intelligence – without relying on a framework to hide the orchestration logic.

---

## What this does

Given a product name and category, the agent runs three analysis tools in sequence – collecting competitive pricing data, 
analyzing customer sentiment, and assessing market trends – then synthesizes everything into a structured business report via a Groq LLM call (or a deterministic fallback if no key is set).

| Tool | What it simulates |
|------|-------------------|
| **ProductCollectorTool** | Scraping product prices, listings, and competitor data from Amazon, Best Buy, eBay, etc. |
| **SentimentAnalyzerTool** | NLP analysis of customer reviews to extract sentiment scores and recurring themes |
| **TrendAnalyzerTool** | 12-month search volume and price history analysis with seasonal pattern detection |

All tools use deterministic mocked data (seeded by product name) – the same request always produces the same output, making the system fully reproducible without external API calls.

The whole thing is exposed through a FastAPI REST interface, runs in Docker, and is designed, so the data flow is traceable without reading framework internals.

---

## Quick Start

```bash
# 1. (Optional) Set Groq API key
export GROQ_API_KEY=gsk_...

# 2. Start
docker-compose up --build

# 3. Check it's alive
curl http://localhost:8000/health

# 4. Submit an analysis
curl -X POST http://localhost:8000/analyze \
  -H "Content-Type: application/json" \
  -d '{"product_name": "iPhone 16 Pro", "category": "consumer electronics", "analysis_depth": "standard"}'

# -> {"job_id": "a73e404b-0881-496b-9036-35e36ddfc3bf", "status": "pending", ...}

# 5. Poll for results
curl http://localhost:8000/analyze/a73e404b-0881-496b-9036-35e36ddfc3bf

# 6. Browse docs
open http://localhost:8000/docs
```
> **Note:** Service works fully without an API key using deterministic fallback synthesis.
> Set `GROQ_API_KEY` to enable LLM-powered report generation.
>
> **Single-worker only:** The in-memory job store is not shared across processes. Run with the default single uvicorn worker (`docker-compose up` as written) — adding `--workers N` would cause `GET /analyze/{job_id}` to return 404 on workers that didn't create the job. See Step 4 for the production storage recommendation.
---

## Architecture & Design Decisions

### Why a custom orchestrator instead of LangGraph, CrewAI, or Google ADK

This was the first decision for me, and it shaped everything else.

Argument for a framework is real; LangGraph handles retries, state persistence, and conditional branching out of the box. 
But for a three-step sequential pipeline where the data dependencies are fixed and well-understood, 
a framework adds a layer of abstraction that makes the control flow harder to read, not easier. I'd be trading explicitness for convenience I don't need here.

More importantly: a custom orchestrator forces every design decision to be written in plain Python. 
Future maintainer can trace what happens when a tool fails, how results accumulate, where the LLM is called, 
and what the fallback path looks like – without consulting framework docs. That auditability was the priority.

The `BaseTool` interface is intentionally framework-agnostic. Wrapping these tools in LangGraph nodes later would be a thin adapter, not a rewrite.

### Data flow: the Blackboard pattern

Every component in the pipeline - tools, executor, agent - passes around a single `AnalysisContext` object. 
Tools read from it (the request parameters), and the orchestrator writes results back into it after each step. 
Nothing is shared through a hidden state; the context is the complete picture of what's happened so far.

This made testing straightforward: unit tests prepopulate the context with fixture data and call individual methods directly, without needing to stand up the full pipeline.

### Required vs optional steps

`ProductCollectorTool` and `TrendAnalyzerTool` are marked required. `SentimentAnalyzerTool` is optional.

The reasoning is that product pricing data and market direction are foundational – without either one, the report would be misleading rather than just incomplete. 
While the Sentiment is an additive signal. If review scraping fails (blocked, rate-limited, no data for that product), the pricing and trend analysis is still actionable. 
The final report notes the gap explicitly but doesn't abort.

This maps to how I'd design this in production. I don't want a transient failure in one data source to take down an entire analysis job.

### LLM for synthesis only, not for orchestration

LLM is called once, after all tools have finished, to write the executive summary and recommendations. 
It never decides which tools to run, never processes raw API responses, and never touches the structured data sections of the report.

There's a version of this where the LLM acts as a planner – deciding which tools to invoke based on the request – but it buys very little here. 
The tool selection logic is dead simple (depth param -> pipeline config), and making it LLM-driven would add latency, non-determinism, and a failure mode with no clear recovery path.

The structured report sections (pricing table, sentiment scores, trend series) are always built directly from tool output. 
LLM output is only used for text. This means the report data is reliable regardless of whether the LLM call succeeds.

### LLM choice: Groq + Llama 3.3 70B

Groq's inference API has two properties that matter here: it's fast (sub-second for this prompt size) and it has a generous free tier, which matters for a prototype that runs locally.

`llama-3.3-70b-versatile` produces consistently structured JSON when prompted correctly. 
I set `temperature=0.2` - low enough to keep output stable, not zero to avoid degenerate token repetition on retries. 
System prompt and schema are stored separately from the builder function (`app/llm/prompts/system.md`, `app/llm/schemas/report_synthesis.json`) so they can be iterated without touching Python code.

### Prompt and schema separation

System prompt lives in `app/llm/prompts/system.md` and the response schema lives in `app/llm/schemas/report_synthesis.json`. 
Dynamic user prompt is built in `app/llm/prompts/builder.py`.

Reasoning behind this approach was a static system prompt is essentially configuration, not logic; Markdown is a better format for it than a Python string literal. 
JSON schema for the LLM response is independently useful (it documents what the LLM is expected to return and could be used for validation). 
Separating these from the Python that uses them means prompt engineers can iterate on them without touching the orchestration code.

### Mocked data

All three tools use deterministic mock data. The same product name always produces the same output – seeded by `abs(hash(product_name.lower())) % 10_000`. 
Five real products (iPhone 16 Pro, iPhone 16, Nike Air Max 270, MacBook Pro 14, Sony WH-1000XM5) have hand-crafted datasets; everything else falls through to category-based generic generation.

This was a deliberate call for this prototype, not a scraping service. 
Also, using real APIs would introduce rate limits, auth overhead, and flakiness into what's meant to be a demo of orchestration design. 
The mock data is realistic enough (plausible prices, actual seasonal patterns, real competitor names) that the LLM synthesis produces coherent output.

---

## Project Structure

```
app/
├── api/                           # FastAPI routes and dependency injection
├── llm/
│   ├── client.py                  # Groq SDK wrapper with fallback handling
│   ├── prompts/
│   │   ├── system.md              # Static system prompt
│   │   └── builder.py             # Dynamic user prompt construction
│   └── schemas/
│       └── report_synthesis.json  # JSON schema injected into user prompt
├── models/                        # Pydantic models: requests, responses, tool outputs
├── orchestrator/
│   ├── agent.py                   # Main orchestrator - coordinates everything
│   ├── context.py                 # AnalysisContext (shared pipeline state)
│   ├── executor.py                # Per-tool retry and timeout handling
│   └── pipeline.py                # Step graph per analysis depth
├── store/                         # In-memory job store
└── tools/
    ├── base.py                    # BaseTool ABC
    ├── product_collector.py
    ├── sentiment_analyzer.py
    └── trend_analyzer.py
```

---

## API Reference

### `POST /analyze`

Submits an analysis job. Returns immediately with a `job_id`; the analysis runs in the background.

```json
{
  "product_name": "iPhone 16 Pro",
  "category": "consumer electronics",
  "target_market": "US market",
  "analysis_depth": "standard"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `product_name` | string | Yes | 2–200 chars |
| `category` | string | Yes | 2–100 chars. Affects sentiment profiles and trend patterns |
| `target_market` | string | No | Default: `"global"` |
| `analysis_depth` | string | No | `"quick"` / `"standard"` / `"deep"`. Default: `"standard"` |

`analysis_depth` options:
- `quick` - product data + trends only (skips sentiment, ~200ms)
- `standard` - all three tools, sentiment optional (default)
- `deep` - same three tools as standard (no behavioral difference in the current prototype); the hook is there for future extension such as including full sentiment themes in the LLM prompt or running a second enrichment pass

**Returns 202** with `{"job_id": "...", "status": "pending"}`.

### `GET /analyze/{job_id}`

Poll until `status` is `completed` or `failed`. On completion, the full `report` object is included.

```json
{
  "status": "completed",
  "report": {
    "executive_summary": "...",
    "product_analysis": { "average_price": 994.0, "market_position": "premium", ... },
    "sentiment_analysis": { "overall_score": 0.62, "label": "positive", ... },
    "market_trends": { "trend_direction": "stable", "momentum_score": 0.71, ... },
    "recommendations": ["...", "..."],
    "confidence_score": 0.85,
    "generated_by": "llm",
    "metadata": { "total_execution_ms": 340.1, "tools_succeeded": 3 }
  }
}
```

Please see `examples/fallback_sample_report_iphone16.json` or `examples/groq_llm_report_iphone16.json` for the full response shape.

### `GET /analyze` - List All Jobs

Returns all jobs in the in-memory store. Useful for demos.

### `GET /health`

```json
{"status": "ok", "version": "1.0.0", "llm_available": true, "llm_model": "llama-3.3-70b-versatile"}
```

---

## Development Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env   # add GROQ_API_KEY for LLM synthesis
uvicorn app.main:app --reload
```

### Running tests

```bash
# Run all tests with coverage
pytest tests/ -v --cov=app --cov-report=term-missing

# Run specific test groups
pytest tests/test_tools/ -v
pytest tests/test_orchestrator/ -v
pytest tests/test_api/ -v

# Run with HTML coverage report
pytest tests/ --cov=app --cov-report=html
open htmlcov/index.html
```
Please see `tests/conftest.py` for test setup. Running `pytest --cov=app --cov-report=html` generates `htmlcov/index.html` with the full line-by-line coverage report.

**Test coverage: 84% overall (88 tests, 0 failures).** The uncovered lines are almost entirely the live Groq API call path in `llm/client.py` and `prompts/builder.py` — tested indirectly through the fallback path and not exercised in CI since no API key is required.

**Test coverage summary:**

| Module | What's tested |
|--------|---------------|
| `test_product_collector` | Known products, unknown products, determinism, price validity |
| `test_sentiment_analyzer` | Score ranges, label validity, determinism, category profiles |
| `test_trend_analyzer` | 12-month timeseries, direction validity, momentum range, determinism |
| `test_pipeline` | Step counts per depth, required/optional flags, step ordering |
| `test_executor` | Successful execution, timeout handling, retry logic |
| `test_agent` | Full run, quick depth, required tool failure, optional tool failure, metadata |
| `test_routes` | All endpoints: 200/202/404/422 responses, end-to-end flow |

---

## Configuration

| Variable | Default | Notes |
|----------|---------|-------|
| `GROQ_API_KEY` | (empty) | Optional - system runs without it |
| `LLM_MODEL` | `llama-3.3-70b-versatile` | Any Groq-hosted model |
| `LLM_MAX_TOKENS` | `1024` | Synthesis output is typically ~300 tokens |
| `TOOL_TIMEOUT` | `10.0` | Per-tool timeout in seconds |
| `MAX_RETRIES` | `2` | Retries on timeout (not on tool failure) |
| `DEBUG` | `false` | Enables debug-level logging |

---

## Theoretical Sections (Steps 4–7)

### Step 4 – Data Architecture and Storage
The current implementation uses an in-memory store for job records and results.

#### 4.1 Data schemas

Currently, the `AnalysisContext` object serves as the in-memory representation of both the request parameters and the accumulated results.

**Analysis Request (input):**
```json
{
  "id": "uuid",
  "product_name": "string",
  "category": "string",
  "target_market": "string",
  "analysis_depth": "quick|standard|deep",
  "created_at": "datetime",
  "client_id": "string"
}
```

**Analysis Result (output):**
```json
{
  "id": "uuid",
  "request_id": "uuid (FK)",
  "status": "pending|running|completed|failed",
  "report": "jsonb",
  "tool_results": "jsonb",
  "generated_by": "llm|fallback",
  "confidence_score": "float",
  "created_at": "datetime",
  "completed_at": "datetime"
}
```

**Tool Cache Entry:**
```json
{
  "cache_key": "sha256(product_name + category + tool_name)",
  "tool_name": "string",
  "data": "jsonb",
  "created_at": "datetime",
  "ttl_seconds": 3600
}
```

> In-memory store works for this prototype with a single uvicorn worker. It falls apart across multiple processes (no shared state between workers) or on restart (all jobs lost). The Quick Start note above flags this explicitly so it's not a silent surprise.

#### 4.2 Storage recommendations and Cache Strategy

For production, I'd layer it as follows:

**PostgreSQL:** as the primary store for job records and results. The report body would go in a `jsonb` column - schema-flexible without losing queryability. Storing the raw tool results alongside the final report matters because it lets us rerun synthesis with a different prompt without re-calling the tools.

**Redis:** for two things: job queue (via Celery or ARQ), and tool-result caching strategy. Caching is straightforward here because the mock data is already deterministic – in production with real scrapers, I'd cache at the tool level with a TTL matched to how fast that data changes (product prices: 1–4h, sentiment aggregates: 6–12h, search trends: 24h). The cache key would be `sha256(product_name.lower() + "|" + category + "|" + tool_name)`.

Alternatively, I can also think of **RabbitMQ** for message queues for asynchronous tasks. I'd use it for the LLM call, which is the longest pole in the tent and can be retried independently of the tools. The API would push a message with the job ID when tools finish, and a separate worker would consume that, call the LLM, and update the DB with the final report.

**S3:** (or equivalent) for large exports – PDF reports, historical snapshots, HTML pages of scraped product, anything that doesn't need to live in the primary DB.

One thing worth thinking about upfront: storing the LLM synthesis input separately from the output. If we ever want to evaluate whether a prompt change improved quality, we need both the input context and the generated output to be queryable. This argues for storing the compressed tool-data summary (what was sent to the LLM) as a column, not just the final report text.
This will server as a request history as well as a reference for future evaluations. 

Storing every `AnalysisRequest` + `AnalysisResult` pair in PostgreSQL. Enables:
- Trend analysis over time ("how has iPhone 16 Pro sentiment shifted over 3 months?")
- Cost attribution per client/product
- ML training data for confidence score calibration

### Step 5 – Monitoring & Observability

#### 5.1 Logging

Structured logging already in place for this prototype (`job_id`, `tool_name`, `execution_time_ms` on every log line) gives us the raw material for most of what we need to monitor and alert on.

#### 5.2 Tracing

The next layer I'd add is OpenTelemetry traces that are one root span per `POST /analyze` request, child spans per tool (`product_collector`, `sentiment_analyzer`, `trend_analyzer`) and per LLM call. 
LLM span specifically should carry token counts as attributes, because that's our cost signal and that's what the cost matters for the client. 
Without that, we're flying blind on how much each analysis actually costs.

#### 5.3 Metrics

For metrics (Prometheus / whatever our stack uses), the key ones:

- `analysis_duration_seconds` histogram - end-to-end latency, broken down by `analysis_depth`
- `tool_execution_seconds` histogram - per-tool, with a `success` label
- `llm_tokens_used_total` counter - per model, so we can see cost trend over time
- `tool_failures_total` counter - per tool, per error type; the alert threshold matters: a required tool failing consistently is a P1, an optional one failing occasionally is noise

The metric I'd watch most closely in practice: the ratio of `generated_by=fallback` to `generated_by=llm`. 
A spike there means either the LLM is down, the API key is expired, or the response is consistently failing JSON parsing. 
All three need different responses.

#### 5.4 Alerting and Monitoring

Thresholds are based on the nature of each failure mode, not arbitrary percentages.

**Required tool failures get zero tolerance.** If `product_collector` or `trend_analyzer` keeps failing, no reports can be produced at all - there's no partial degradation, just outage. 
So the alert fires if a required tool fails continuously for 2 minutes (CRITICAL). 
An optional tool like `sentiment_analyzer` failing occasionally is noise; it shows up in the high error rate alert if it becomes persistent.

**Overall job failure rate** covers the catch-all: if more than 5% of jobs fail over a 5-minute window for any reason, something is wrong.

**LLM fallback rate** is the most useful leading indicator for LLM health - more reliable than raw latency because it captures the end state (did we get a useful report or not?). 
Alert if fallback exceeds 10% of analyses in a 1-hour window. A spike here means either the LLM is down, the API key expired, or JSON parsing is consistently failing - each needs a different response.

**LLM latency** independently still matters for user experience. Alert if p95 of `llm_synthesis_duration_seconds` exceeds 10s - Groq is typically sub-second, 
so the 10s means something structural is wrong, not just a slow request.

**Cost spike**: alert if the per-hour token rate exceeds 2× the 7-day rolling average. This catches both runaway usage and prompt changes that accidentally bloat token counts.

| Alert | Condition | Severity |
|-------|-----------|----------|
| Required tool down | `tool_failures{required=true} > 0` sustained 2m | CRITICAL |
| High job failure rate | `analysis_failure_rate > 5%` over 5m | WARNING |
| LLM fallback rate | `fallback_rate > 10%` over 1h | WARNING |
| LLM latency spike | `p95 llm_synthesis_duration_seconds > 10s` | WARNING |
| Queue backlog | `job_queue_depth > 100` | WARNING |
| LLM cost spike | `rate(llm_tokens_used_total[1h]) > 2x 7d baseline` | WARNING |

#### 5.5 Output Quality Measurement

I'd design the output quality measurement strategy around two distinct layers, each with different measurement strategies.

**Layer 1: Structured data sections** (`product_analysis`, `sentiment_analysis`, `market_trends`) are always built deterministically from tool outputs. 
Quality here is about data completeness and schema correctness and easy to measure with automated checks on every response:

- Did all expected fields populate? (`average_price > 0`, `recommendations` list non-empty, `confidence_score` in `[0, 1]`)
- Does `generated_by` match actual LLM availability? (If `GROQ_API_KEY` is set and the call succeeded, `generated_by` must be `"llm"`)
- Is `confidence_score` internally consistent with tool coverage? (three tools succeeded -> the score should be ≥ 0.75; 2 tools -> 0.55–0.75)

These run synchronously after every synthesis call. They're cheap and catch silent failures; kind where the report looks complete but the numbers are wrong.

**Layer 2: LLM-generated narrative** (`executive_summary`, `recommendations`) is where it gets harder. Two complementary approaches:

**Faithfulness check (rule-based, runs on every report):**
Executive summary must not contradict the structured data that was built alongside it. Since both live in the same `MarketReport` object, this is checkable without a second LLM call:

- If `market_position == "premium"`, summary must not contain "affordable" or "budget"
- If `trend_direction == "declining"`, summary must not describe demand as "strong" or "growing"
- If `sentiment_analysis` is `None` (quick depth or tool failed), summary must not reference customer reviews or sentiment scores

These are lightweight string checks, but they catch the most damaging class of failure: a report that looks authoritative but silently contradicts its own data.

**LLM-as-Judge:**
After synthesis, queue an evaluation job that sends both the compressed tool input and the generated report to a judge model. 
I'd use a different provider here because if Groq is having issues, judge model shouldn't be affected by the same failure. 
Judge scores three dimensions with a rubric:

```
Given this market data:
{compressed_tool_summary}

And this generated report:
{executive_summary + recommendations}

Score 1–5 on:
- Faithfulness: do all claims trace back to the data provided?
- Actionability: are recommendations specific enough to act on, or generic advice?
- Completeness: does the summary address pricing, sentiment, and trend signals proportionally?

Return JSON: {"faithfulness": N, "actionability": N, "completeness": N, "issues": ["..."]}
```

Sampling rate: 100% during prompt iteration, 10–20% in steady-state production. 
Store every score in the DB with the `job_id` so we can correlate quality drops with specific prompt changes or model updates.

**Tracking quality over time:**
The metrics that matter most to track as a trend, not just spot-check:

- 7-day rolling average of LLM-as-Judge scores per dimension – a drop of > 0.3 on any single dimension triggers a review
- Distribution of `confidence_score` values - a shift toward lower scores without a corresponding change in tool failure rate suggests the LLM is producing weaker output
- Rate of faithfulness check failures – even one per day is worth investigating

**One thing I would explicitly avoid:** running LLM-as-Judge synchronously in the hot path on every request. 
Rule-based faithfulness checks are the right synchronous safety net — they're cheap and don't depend on a second LLM being available. LLM-as-Judge should run async and sampled, not inline.

---

### Step 6 – Scaling & Optimisation

#### 6.1 API scaling (Handle load peaks)
Current architecture runs analysis synchronously in FastAPI background tasks, which means analysis throughput is limited by the number of uvicorn workers. 
That's fine for this prototype; it breaks under a concurrent load because each analysis ties up a worker thread.

For **Production solution**:
I'd move to make is decoupling HTTP from analysis: the API creates a job record and pushes to a task queue (Redis/Celery or ARQ), workers pull jobs independently. 
We can then scale workers horizontally without touching the API layer.

```
HTTP API (FastAPI)
       │  submit job
       ▼
  Job Queue (Redis/Celery)
       │  async worker picks up job
       ▼
  Worker Pool (N worker processes)
       │  each runs MarketAnalysisAgent
       ▼
  PostgreSQL (job state) + Redis (cache)
```

Scale workers horizontally: `docker-compose scale worker=10`

#### 6.2 Tool Parallelisation

In the current implementation all three tools run sequentially. That was a deliberate choice for the prototype — a linear for-loop makes the control flow obvious when reading the code, which was the priority here.

In production, `SentimentAnalyzer` and `TrendAnalyzer` have **no data dependency on each other** — both only need the initial request. So once `ProductCollector` completes, the other two can run concurrently with `asyncio.gather`. 
That alone cuts the sequential portion of the pipeline from three tool latencies to two, which matters once the tools are hitting real APIs with real network latency.

#### 6.3 LLM Prompt Optimization and Caching Strategy

Currently, the synthesis prompt is already compressed to ~500 tokens. Further reduction: drop sample reviews, truncate forecast text, and replace verbose competitor lists with counts and price ranges.

On top of that what I would do for LLM cost optimization:
- **Cache synthesis by data hash** — if two requests produce identical tool data (same product + same cache hit), reuse the LLM response. Cache key: `SHA256(compressed_tool_data)`. At scale, this could cut LLM calls by 60–70% for popular products.

### Step 7 – Continuous Improvement & A/B Testing

The thing I care most about here is catching prompt regressions. The risk with any LLM-in-the-loop system is that a prompt change that looks like an improvement in manual spot-checking turns out to degrade quality at scale.

#### 7.1 Automated quality evaluation (LLM-as-Judge)

As I mentioned earlier in the section on monitoring, the practical approach would be after each synthesis, run a second LLM call (evaluator model) that scores the output on three dimensions: 

- Factual grounding (does the summary contradict the data?), 
- Actionability (are the recommendations specific?), 
- Completeness (does it address all three data signals?). 

Store those scores in the PostgreSQL. Set an alert if the 7-day rolling average drops by more than 0.3 points on any dimension.

#### 7.2 A/B Testing prompts variants

For A/B testing prompts specifically: route requests to prompt variants based on a deterministic bucket derived from `job_id` (e.g., `int(job_id[-2:], 16) % 100`). 
This gives a stable assignment without session tracking. 

We can design a system for tracking these variants. For example:

```python
class SynthesisVariant(Enum):
    CONTROL = "v1_detailed"        # current prompt
    VARIANT_A = "v2_concise"       # 30% shorter prompt, less context
    VARIANT_B = "v3_structured"    # step-by-step chain-of-thought

# Traffic split: 70% control, 15% A, 15% B
def select_variant(job_id: str) -> SynthesisVariant:
    bucket = int(job_id[-2:], 16) % 100
    if bucket < 70: return SynthesisVariant.CONTROL
    if bucket < 85: return SynthesisVariant.VARIANT_A
    return SynthesisVariant.VARIANT_B
```

And track per-variant: LLM-as-judge scores, token usage, and eventually any user feedback signal. Variants with statistically worse scores get rolled back; winning variants get promoted and the old ones retired.

#### 7.3 User feedback loop
I'd add a user feedback loop to the system. Naturally, the feedback loop that matters most in practice: 
when a user looks at a report and does something with it (exports it, shares it, uses a recommendation), that's the clear signal that the report was useful. 
Implicit engagement beats explicit ratings for coverage. Hard to implement without a frontend, but worth designing the data model for from day one.

Another thing I'd add is a "Report Issue" button in the UI that lets users flag a report as inaccurate or unhelpful. This would create a feedback record linked to the `job_id`, which we can then use to correlate with LLM-as-Judge scores and identify failure patterns that automated checks might miss.

For example,

```json
{"rating": 4, "useful_sections": ["recommendations"], "missing": "competitor pricing history"}
```

Use feedback to:
1. Identify which report sections users find most valuable (weight in confidence score)
2. Surface data gaps (what users expect but the tools don't provide)
3. Fine-tune the LLM-as-Judge prompt to align with user preferences
