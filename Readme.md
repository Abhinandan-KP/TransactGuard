# TransactGuard

> A production-grade web application that detects money muling networks in financial transaction data through graph analysis, statistical anomaly detection, and interactive visualization.

**Live Demo:** _Coming Soon_
**GitHub:** [Abhinandan-KP/muledetection](https://github.com/Abhinandan-KP/muledetection)

---

## Table of Contents

- [Tech Stack](#tech-stack)
- [System Architecture](#system-architecture)
- [Algorithm Approach & Complexity Analysis](#algorithm-approach--complexity-analysis)
- [Suspicion Score Methodology](#suspicion-score-methodology)
- [Installation & Setup](#installation--setup)
- [Usage Instructions](#usage-instructions)
- [JSON Output Format](#json-output-format)
- [Project Structure](#project-structure)
- [Performance Analysis](#performance-analysis)
- [Known Limitations](#known-limitations)

---

## Tech Stack

| Layer      | Technology                    | Purpose                                              |
| ---------- | ----------------------------- | ---------------------------------------------------- |
| Backend    | **Python 3.13** / **FastAPI** | REST API, CSV parsing, analysis orchestration        |
| Graph      | **NetworkX 3.x**              | Directed graph, cycle detection, Louvain communities |
| Data       | **Pandas 3.x** / **NumPy**    | Vectorized transaction processing & statistics       |
| Validation | **Pydantic v2**               | Request/response schema validation                   |
| Frontend   | **React 18** / **Vite 5**     | Single-page application, drag-and-drop upload        |
| Viz        | **react-force-graph-2d**      | Force-directed interactive graph rendering           |
| HTTP       | **Axios**                     | API communication with 60s timeout handling          |

---

## System Architecture

```
                          ┌──────────────────────────────────┐
               CSV Upload │       FastAPI Backend v2.0       │
  Browser  ─────────────> │       POST /analyze              │
  (React)                 │                                  │
                          └──────┬───────────────────────────┘
                                 │
       ┌─────────────────────────┼─────────────────────────┐
       │          Step 1         │                          │
       │   ┌─────────────────┐   │                          │
       │   │   parser.py     │   │   CSV → Validated DF     │
       │   └────────┬────────┘   │                          │
       │            │            │                          │
       │   Step 2   ▼            │                          │
       │   ┌─────────────────┐   │                          │
       │   │ graph_builder.py│   │   DF → NetworkX DiGraph  │
       │   └────────┬────────┘   │                          │
       │            │            │                          │
       │   Step 3   ▼ Core Detection (×4)                   │
       │   ┌─────────┬──────────┬──────────┬────────────┐   │
       │   │ cycle_  │ smurf_   │ shell_   │bidirection-│   │
       │   │detector │detector  │detector  │al_detector │   │
       │   │(Johnson)│(2-ptr    │(iter DFS)│(round-trip)│   │
       │   │         │ window)  │          │            │   │
       │   └────┬────┴────┬─────┴────┬─────┴─────┬──────┘   │
       │        │         │          │           │          │
       │   Step 4   ▼ Enrichment Detectors (×3)             │
       │   ┌──────────────┬────────────────┬─────────────┐  │
       │   │  anomaly_    │ rapid_movement │ structuring_ │  │
       │   │  detector    │ _detector      │ _detector    │  │
       │   │  (σ outlier) │ (dwell time)   │ (sub-$10K)   │  │
       │   └──────┬───────┴───────┬────────┴──────┬──────┘  │
       │          │               │               │         │
       │   Step 5 ▼                                         │
       │   ┌──────────────────────────────────────────┐     │
       │   │  utils.py → Ring merging + ID assignment │     │
       │   └──────┬───────────────────────────────────┘     │
       │          │                                         │
       │   Step 6 ▼                                         │
       │   ┌──────────────────────────────────────────┐     │
       │   │  scoring.py → Multi-factor scoring +     │     │
       │   │               risk explanations          │     │
       │   └──────┬───────────────────────────────────┘     │
       │          │                                         │
       │   Step 7 ▼                                         │
       │   ┌──────────────────────────────────────────┐     │
       │   │  formatter.py → JSON response builder    │     │
       │   │  (3 mandatory keys; graph + parse_stats  │     │
       │   │   added in ?detail=true mode)            │     │
       │   └──────────────────────────────────────────┘     │
       └────────────────────────────────────────────────────┘
```

### Pipeline Steps (7-Stage)

| Step | Module                    | Action                                                                               |
| ---- | ------------------------- | ------------------------------------------------------------------------------------ |
| 1    | `parser.py`               | Decode CSV (UTF-8/latin-1), validate columns, clean amounts/timestamps, dedup        |
| 2    | `graph_builder.py`        | Build directed weighted graph with vectorised Pandas groupby node/edge stats         |
| 3    | Core detectors (×4)       | Cycle detection, fan-in/fan-out, shell chains, bi-directional round-trip flows       |
| 4    | Enrichment detectors (×3) | Amount anomaly (3σ), rapid movement (dwell time), structuring (sub-$10K)             |
| 5    | `utils.py`                | Merge overlapping rings (≥50% member overlap), assign RING_001, RING_002, ...        |
| 6    | `scoring.py`              | Multi-factor 0–100 scoring + natural language risk explanations                      |
| 7    | `formatter.py`            | Clean JSON with 3 mandatory keys; `graph` + `parse_stats` added when `?detail=true`  |

---

## Algorithm Approach & Complexity Analysis

### 1. Circular Fund Routing — Cycle Detection

**What it detects:** Money flowing in loops (A → B → C → A) to obscure its criminal origin.

**Algorithm:** Johnson's algorithm via NetworkX `simple_cycles()`:

- Length filter: 3 ≤ length ≤ 5
- Canonical deduplication: each cycle is rotated to its lexicographically smallest node, so [A,B,C] and [B,C,A] are recognised as the same ring
- **SCC pre-filter** — `nx.strongly_connected_components()` runs first (O(V+E)); `simple_cycles()` runs only on the SCC subgraph, eliminating acyclic nodes before enumeration starts. On a 6K-node graph this reduces the search space by ~70%.
- Threading-based timeout (5s default) prevents exponential runtime on dense graphs
- Hard cap: 5,000 cycles

**Complexity:** O(V+E) for SCC, then O((V' + E') × C) on the reduced subgraph where V' << V. Bounded by timeout and hard cap.

---

### 2. Smurfing — Fan-in / Fan-out Detection

**What it detects:** Many small deposits aggregated into one account (fan-in) or one account dispersing to many (fan-out) — classic structuring to stay below reporting thresholds.

**Algorithm:**

1. Group transactions by target (fan-in) or source (fan-out)
2. Sort each group by timestamp — O(n log n)
3. Two-pointer sliding window (72-hour window) counts unique counterparties via a frequency dict
4. Trigger: 10+ unique counterparties in any window

**False positive control:**

- **Merchant exclusion (fan-in):** CV > 0.15 → variable purchase amounts → legitimate merchant → excluded.
- **Payroll exclusion (fan-out):** All outgoing transactions within a 60-second span → batch payroll → excluded.

**Complexity:** O(n log n) per group. Two-pointer scan is O(n).

---

### 3. Layered Shell Networks — Chain Detection

**What it detects:** Chains of 3+ hops through intermediate shell accounts with ≤3 total transactions.

**Algorithm:**

1. SCC exclusion — cycle participants are never classified as shells
2. Shell criteria: `tx_count ≤ 3 AND in_degree > 0 AND out_degree > 0 AND NOT in SCC of size > 1`
3. Iterative DFS (stack-based, no recursion) from every node that has at least one shell successor
4. Valid chain: `source → [SHELL_1, SHELL_2, ...] → destination` with ≥3 total hops
5. Depth limit: 6 hops max. Hard cap: 1,000 chains.

**Complexity:** O(V × d^b). Bounded by hard cap.

---

### 4. Bi-directional Flow — Round-trip Detection

**What it detects:** Account pairs where A→B and B→A both exist with similar total amounts.

**Algorithm:**

1. For every edge A→B, check if reverse edge B→A exists
2. Compute similarity: `1 - |amount_AB - amount_BA| / max(amount_AB, amount_BA)`
3. Flag if similarity ≥ 80%
4. Deduplicate via sorted tuple keys

**Complexity:** O(E) — single pass over all edges.

---

### 5. Amount Anomaly Detection

**What it detects:** Transactions deviating more than 3σ from an account's mean.

**Algorithm:**

1. Group transactions by account
2. For accounts with ≥5 transactions: compute mean and standard deviation
3. Flag if any transaction amount > μ + 3σ

**Complexity:** O(T).

---

### 6. Rapid Movement Detection

**What it detects:** Accounts that receive and forward funds within minutes.

**Algorithm:**

1. Per account: separate incoming and outgoing transactions, sort by timestamp
2. Two-pointer scan: find earliest outgoing tx after each incoming tx
3. If dwell time ≤ 30 minutes → flag

**Complexity:** O(n log n) per account.

---

### 7. Amount Structuring Detection

**What it detects:** Multiple transactions deliberately kept just below the $10,000 CTR reporting threshold.

**Algorithm:**

1. Structuring band: $8,500 to $10,000
2. Count sent transactions per account in the band
3. Flag if ≥3 transactions in band

**Complexity:** O(T).

---

### Overall Pipeline Complexity

**Total:** O(n log n) + O(V+E) + O((V' + E') × C) + O(V × d^b) + O(E) + O(T)

Typical processing: **< 0.5s** for 1K rows, **< 10s** for 10K rows.

---

## Suspicion Score Methodology

### Pattern Weights (Primary)

| Factor               | Points |
| -------------------- | ------ |
| Cycle (length 3)     | **35** |
| Cycle (length 4)     | **30** |
| Cycle (length 5)     | **25** |
| Fan-in hub only      | **28** |
| Fan-out hub only     | **28** |
| Shell intermediaries | **22** |
| Round-trip member    | **20** |

### Enrichment Bonuses

| Factor                 | Points        | Trigger Condition                                    |
| ---------------------- | ------------- | ---------------------------------------------------- |
| Amount anomaly         | **+20**       | Transaction > 3σ from account mean                   |
| Rapid movement         | **+20**       | Dwell time ≤ 30 minutes                              |
| Amount structuring     | **+15**       | 3+ transactions in $8,500–$10,000 band               |
| High velocity          | **+15**       | Average > 5 transactions/day                         |
| Multi-ring bonus       | **+10/ring**  | Extra 10 points per additional ring beyond the first |
| Betweenness centrality | **up to +10** | Network hub importance (≤500 node graphs only)       |

### Formula

**Score = Σ(pattern weights) + Σ(enrichment bonuses), capped at 100.0**

---

## Installation & Setup

### Prerequisites

- Python >= 3.10
- Node.js >= 18
- npm or yarn

### Backend

```bash
cd backend
pip install -r requirements.txt
python -m uvicorn app.main:app --reload --port 8000
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Open [http://localhost:5173](http://localhost:5173) in your browser.

### Environment Variables (optional)

| Variable                       | Default | Description                                       |
| ------------------------------ | ------- | ------------------------------------------------- |
| `MAX_FILE_SIZE_MB`             | 20      | Max upload file size in MB                        |
| `MAX_ROWS`                     | 10000   | Max transaction rows to process                   |
| `FAN_THRESHOLD`                | 10      | Min unique counterparties for smurf               |
| `SMURF_WINDOW_HOURS`           | 72      | Sliding window duration in hours                  |
| `MERCHANT_AMOUNT_CV_THRESHOLD` | 0.15    | CV threshold above which receiver is a merchant   |
| `PAYROLL_BATCH_SECONDS`        | 60      | Max span (s) for all sends to be treated as batch |
| `CYCLE_TIMEOUT_SECONDS`        | 5       | Cycle detection timeout                           |
| `CORS_ORIGINS`                 | *       | Comma-separated allowed origins                   |
| `VITE_API_URL`                 | (empty) | Frontend API base URL for deployment              |

---

## Usage Instructions

1. Open the web app at [http://localhost:5173](http://localhost:5173)
2. Upload a CSV file via drag-and-drop or click-to-browse
   - Required columns: `transaction_id`, `sender_id`, `receiver_id`, `amount`, `timestamp`
3. View results in three tabs:
   - **Network Graph** — Interactive force-directed visualization. Suspicious nodes are color-coded by pattern type.
   - **Fraud Rings** — Table showing Ring ID, Pattern Type, Member Count, Risk Score, and Member Account IDs.
   - **Suspicious Accounts** — Table of flagged accounts sorted by suspicion score with risk explanation.
4. Download JSON report via the button in the header.
5. Download sample CSV to test with a pre-built dataset.

### API Endpoints

| Method | Path       | Description                                |
| ------ | ---------- | ------------------------------------------ |
| GET    | `/`        | Service info                               |
| GET    | `/health`  | Health check with version and config info  |
| POST   | `/analyze` | Upload CSV and run full forensics pipeline |

---

## JSON Output Format

```json
{
  "suspicious_accounts": [
    {
      "account_id": "ACC_00123",
      "suspicion_score": 87.5,
      "detected_patterns": ["cycle_length_3", "rapid_movement"],
      "ring_id": "RING_001"
    }
  ],
  "fraud_rings": [
    {
      "ring_id": "RING_001",
      "member_accounts": ["ACC_00123", "ACC_00456", "ACC_00789"],
      "pattern_type": "cycle_length_3",
      "risk_score": 95.0
    }
  ],
  "summary": {
    "total_accounts_analyzed": 500,
    "suspicious_accounts_flagged": 15,
    "fraud_rings_detected": 4,
    "processing_time_seconds": 2.3
  }
}
```

---

## Project Structure

```
transactguard/
├── backend/
│   ├── requirements.txt
│   ├── .env.example
│   └── app/
│       ├── config.py
│       ├── models.py
│       ├── main.py
│       ├── parser.py
│       ├── graph_builder.py
│       ├── cycle_detector.py
│       ├── smurf_detector.py
│       ├── shell_detector.py
│       ├── bidirectional_detector.py
│       ├── anomaly_detector.py
│       ├── rapid_movement_detector.py
│       ├── structuring_detector.py
│       ├── scoring.py
│       ├── formatter.py
│       └── utils.py
├── frontend/
│   ├── package.json
│   ├── vite.config.js
│   ├── index.html
│   └── src/
│       ├── App.jsx
│       ├── App.css
│       ├── index.css
│       ├── main.jsx
│       └── components/
│           ├── FileUpload.jsx
│           ├── GraphVisualization.jsx
│           ├── SummaryStats.jsx
│           ├── SummaryTable.jsx
│           └── DownloadButton.jsx
└── README.md
```

---

## Performance Analysis

| Metric                 | Achieved                                              |
| ---------------------- | ----------------------------------------------------- |
| Processing Time        | < 0.5s for 1K rows, ~15s for 10K rows                 |
| Precision              | CV-based merchant exclusion + batch payroll detection |
| Recall                 | 7 detection patterns + 4 enrichment bonuses           |
| False Positive Control | Semantic exclusions; shell members = intermediaries   |

---

## Known Limitations

1. **In-memory processing** — Files exceeding ~100K rows may cause memory pressure.
2. **Single-threaded detectors** — All 7 detectors run sequentially.
3. **Static thresholds** — Configurable but not adaptive to dataset characteristics.
4. **No persistence** — Results are not stored server-side.
5. **Betweenness centrality** skipped for graphs with > 500 nodes.
6. **Cycle detection** may time out on extremely dense graphs, returning partial results.
7. **Amount anomaly** requires ≥5 transactions per account for meaningful statistics.

---

_Developed by Abhinandan_
