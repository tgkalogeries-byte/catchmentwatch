# CatchmentWatch

I built CatchmentWatch as a public-data prototype for flood situational awareness. It brings Environment Agency flood alerts, river-level readings, station reference ranges and nearby rainfall readings into one evidence queue. The aim is to help an analyst decide what to inspect next and see the source behind each signal.

## Why it is useful

Operational teams often work across separate alert and monitoring feeds. CatchmentWatch demonstrates a small data-fusion workflow: it joins latest readings to their station metadata, compares a gauge with its own published typical-range reference, and adds the nearest rainfall monitor as geographic context. It keeps official alerts separate from locally calculated screening cues.

## What it can say

- Which available stations have readings above the station's published typical-range high value.
- What the nearest available rainfall monitor reports, how far away it is, and when that reading was observed.
- Which official flood alerts and warnings the Environment Agency API currently returns.
- Which feeds failed and how many readings were successfully matched.
- For a selected station pair, the hourly rainfall/river-level series, a 1–12 hour lag candidate selected on the earlier 70% of the window, and its correlation in the later 30% holdout. Training pairs are kept entirely before the time split so future level readings cannot leak into candidate selection.

The nearest rain gauge is chosen by straight-line distance. That is context only; it does not prove the rain gauge and river station share a catchment or that rainfall caused a river-level change. The lag scan selects a positive 1–12 hour training-period correlation, then checks it against later observations. A candidate must have a holdout correlation of at least 0.20 and improve by at least 0.10 over a same-hour baseline to pass the app's transparent screening rules. These cut-offs are practical filters, not significance tests. They do not establish predictive skill; correlations remain vulnerable to temporal dependence and the lag search involves multiple comparisons. In the live sample checked on 5 November 2026 (station 4203 with nearby rainfall station 4163), the chosen one-hour lag had training r≈0.56 but holdout r≈0.06, below the screening rules. That is weak evidence and does not establish a useful or repeatable signal. “Above typical range” is not an official flood threshold. This prototype does not forecast floods, estimate property risk, or replace official warnings and emergency procedures.

## Data source

The application reads live, open data from the Environment Agency's [real-time flood-monitoring API](https://environment.data.gov.uk/flood-monitoring/doc/reference). It requests station metadata, latest water-level and rainfall readings, and current flood alerts. The API is a beta service, updates arrive at different rates, and it is not a safety-critical service. The API documentation describes its coverage, endpoints and update limitations.

## Run locally

Requires Python 3.11 or newer.

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e .
uvicorn catchmentwatch.main:app --app-dir src --reload
```

Open <http://127.0.0.1:8000>. The API snapshot is cached for ten minutes; use **Refresh sources** to request a new snapshot. Interactive API docs are at <http://127.0.0.1:8000/docs>.

## Design

- `sources.py` fetches the three public feed types, joins reading records to station measures, keeps partial feed failures visible, and adds nearest-rainfall context.
- `main.py` exposes a small HTTP API with a short in-memory cache.
- `static/` renders an evidence-first dashboard with search, source timestamps and explicit limits.

The next analytical milestone is a historical backtest: evaluate the lag scan on archived periods, compare it with simple baselines, and measure stability across multiple catchments before making any predictive claim.

## Skills demonstrated

CatchmentWatch is relevant to data analyst, data science, software engineering, systems engineering and public-sector digital roles. It demonstrates API integration, data normalization, time-stamped source joins, bounded caching, partial-failure handling, statistical reference comparisons, explainable screening cues, accessible dashboard patterns and explicit data limitations. It does not claim to be a deployed warning service.

## Further development

1. Add historical snapshots and durable provenance hashes.
2. Build catchment-aware links from official hydrology metadata instead of using proximity as a proxy.
3. Add a retrospective, time-ordered evaluation and report precision, recall and lead-time distributions.
4. Add map-based exploration, accessibility review, monitoring and rate-limit/backoff handling.
5. Add an optional Rust stream processor if measured data volume or throughput justifies it; Python currently handles the small prototype's joins and presentation.

## Status

Published portfolio prototype. It depends on live network access to the Environment Agency API and is not intended for emergency or safety-critical decisions.
