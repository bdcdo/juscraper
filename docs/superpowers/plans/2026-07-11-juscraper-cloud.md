# juscraper-cloud Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a vendor-neutral companion distribution that routes existing juscraper sessions through an HTTP(S) proxy and supports local or remote Playwright execution for eproc deployments that require a real browser.

**Architecture:** A nested `packages/juscraper-cloud` distribution depends on the repository's `juscraper` package without changing the upstream factory. Its wrapper delegates supported courts to `juscraper.scraper`, applies a whole-session `ProxyRoute`, and owns experimental TRF2/TRF4 eproc clients backed by a public `BrowserProvider` protocol. Provider-specific experiments stay outside the published package.

**Tech Stack:** Python 3.11+, uv, hatchling, requests, pydantic, pandas, pytest, optional Playwright Python.

## Global Constraints

- Keep all published APIs and documentation vendor-neutral.
- Each user supplies their own proxy or browser endpoint credentials.
- A configured proxy applies to the scraper's entire `requests.Session`; there is no direct-first fallback.
- Precedence is explicit argument, then `JUSCRAPER_PROXY_URL`, then direct networking.
- Never log, repr, or persist proxy credentials.
- Support a custom CA bundle; never fall back to `verify=False`.
- Browser automation is deterministic Playwright code; no LLM prompts.
- Preserve `sleep_time >= 1.0` in TRF browser clients and do not add aggressive concurrency.
- Keep provider-specific adapters and comparisons under `experiments/`, outside wheel/sdist contents and user documentation.
- Do not modify the upstream `juscraper` public API or register TRF2/TRF4 in its closed factory.

---

### Task 1: Companion Package and Proxy Route

**Files:**
- Create: `packages/juscraper-cloud/pyproject.toml`
- Create: `packages/juscraper-cloud/src/juscraper_cloud/__init__.py`
- Create: `packages/juscraper-cloud/src/juscraper_cloud/errors.py`
- Create: `packages/juscraper-cloud/src/juscraper_cloud/network.py`
- Create: `packages/juscraper-cloud/src/juscraper_cloud/factory.py`
- Create: `packages/juscraper-cloud/tests/test_network.py`
- Create: `packages/juscraper-cloud/tests/test_factory.py`

**Interfaces:**
- Produces `ProxyRoute(url: str, ca_bundle: str | Path | None = None)` with `from_env()` and `apply(session)`.
- Produces `scraper(sigla: str, *, route: ProxyRoute | None = None, browser: BrowserProvider | None = None, **kwargs)`; Task 1 supports only delegation to the upstream factory and rejects non-`None` browser values.
- Produces `ProxyConfigurationError`, `RemoteTransportError`, `RemoteQuotaError`, and `BrowserChallengeError`.

- [ ] **Step 1: Write failing proxy tests**

  Cover explicit values, environment loading, missing/invalid scheme, missing CA bundle, applying both HTTP and HTTPS proxy entries, CA assignment to `session.verify`, and credential-redacted `repr`.

- [ ] **Step 2: Run proxy tests and verify RED**

  Run: `uv run --project packages/juscraper-cloud pytest tests/test_network.py -q`

  Expected: collection failure because `juscraper_cloud.network` does not exist.

- [ ] **Step 3: Implement package metadata, errors, and `ProxyRoute`**

  Use a frozen dataclass with a private parsed URL helper. Accept only `http` and `https`; require hostname; preserve the original secret only for `Session.proxies`; redact `username`, `password`, and query values in `repr`. `from_env()` reads `JUSCRAPER_PROXY_URL` and `JUSCRAPER_PROXY_CA_BUNDLE`, returning `None` when the URL is unset.

- [ ] **Step 4: Run proxy tests and verify GREEN**

  Run: `uv run --project packages/juscraper-cloud pytest tests/test_network.py -q`

- [ ] **Step 5: Write failing factory tests**

  Verify delegation of positional API kwargs, whole-session proxy application, environment fallback, unchanged return object, helpful failure when the delegated object lacks a `requests.Session`, route rejection for the future browser-only `trf2`/`trf4` names, and rejection of a browser argument for upstream scrapers.

- [ ] **Step 6: Run factory tests and verify RED**

  Run: `uv run --project packages/juscraper-cloud pytest tests/test_factory.py -q`

- [ ] **Step 7: Implement wrapper factory and public exports**

  Import the upstream factory lazily. Validate `scraper.session` with `isinstance(..., requests.Session)` before applying a route. Never mutate global `HTTP_PROXY`/`HTTPS_PROXY` variables.

- [ ] **Step 8: Run Task 1 tests and commit**

  Run: `uv run --project packages/juscraper-cloud pytest -q`

  Commit: `feat(cloud): adiciona rota de proxy neutra`

---

### Task 2: Open Playwright Browser Providers

**Files:**
- Modify: `packages/juscraper-cloud/pyproject.toml`
- Create: `packages/juscraper-cloud/src/juscraper_cloud/browser.py`
- Create: `packages/juscraper-cloud/tests/test_browser.py`

**Interfaces:**
- Produces runtime-checkable `BrowserProvider` protocol with `open_page() -> ContextManager[Page]`.
- Produces `LocalPlaywrightProvider(headless: bool = True, proxy_server: str | None = None)`.
- Produces `PlaywrightWsProvider(endpoint: str, headers: Mapping[str, str] | None = None)`.
- Produces `CdpPlaywrightProvider(endpoint: str, headers: Mapping[str, str] | None = None)`.
- All providers own and close contexts/pages/connections they create, including exceptional exits.

- [ ] **Step 1: Write failing provider lifecycle tests**

  Use fake Playwright objects to verify local launch, WebSocket connect, CDP connect, existing default-page reuse for CDP, fresh context creation where supported, header forwarding, and cleanup on success/failure. Assert repr redacts endpoint userinfo and query tokens.

- [ ] **Step 2: Run provider tests and verify RED**

  Run: `uv run --project packages/juscraper-cloud pytest tests/test_browser.py -q`

- [ ] **Step 3: Implement the providers behind an optional import**

  Add optional dependency group `browser = ["playwright>=1.52"]`. Import Playwright only inside `open_page()` and raise an `ImportError` instructing installation of `juscraper-cloud[browser]`. Prefer `BrowserType.connect()` for Playwright endpoints and use `connect_over_cdp()` only for CDP endpoints.

- [ ] **Step 4: Run provider tests and verify GREEN**

  Run: `uv run --project packages/juscraper-cloud pytest tests/test_browser.py -q`

- [ ] **Step 5: Run a real local Playwright smoke test**

  Install Chromium with `uv run --project packages/juscraper-cloud playwright install chromium`, serve a local static page, open it through `LocalPlaywrightProvider`, and assert its title. Keep the smoke test marked `browser_integration` and excluded by default.

- [ ] **Step 6: Run Task 2 tests and commit**

  Run: `uv run --project packages/juscraper-cloud pytest -q`

  Commit: `feat(cloud): adiciona providers Playwright abertos`

---

### Task 3: Browser-backed eproc TRF2/TRF4 Clients

**Files:**
- Create: `packages/juscraper-cloud/src/juscraper_cloud/eproc.py`
- Create: `packages/juscraper-cloud/src/juscraper_cloud/trf.py`
- Modify: `packages/juscraper-cloud/src/juscraper_cloud/factory.py`
- Modify: `packages/juscraper-cloud/src/juscraper_cloud/__init__.py`
- Create: `packages/juscraper-cloud/tests/test_eproc.py`
- Create: `packages/juscraper-cloud/tests/test_trf.py`
- Reuse fixtures: `tests/trf6/samples/cpopg/*.html`

**Interfaces:**
- Produces `EprocDeployment(name: str, base_url: str)` and predefined deployment maps for TRF2 (`rj`, `es`) and TRF4 (`pr`, `sc`, `rs`).
- `scraper("trf2", browser=provider, deployment="rj", sleep_time=1.0)` and `scraper("trf4", browser=provider, deployment="rs", sleep_time=1.0)` require an explicit deployment in the first release.
- Produces `TRF2CloudScraper` and `TRF4CloudScraper` with `cpopg`, `cpopg_download`, and `cpopg_parse`, validating inputs through a package-local pydantic schema with `extra="forbid"`.
- The downloader fills the public eproc process-number field, waits for the challenge token or detail page, submits, waits for either detail/no-result/error state, and returns raw HTML. Parsing delegates to `juscraper.courts.trf6.parse.parse_detail` only after fixture parity proves the shared eproc shape.

- [ ] **Step 1: Write failing deterministic eproc-flow tests**

  Build a fake Playwright Page that records `goto`, locator selection, `fill`, `click`, waits, and `content`. Verify formatted CNJ input, explicit deployment URL, no-result handling, challenge timeout mapping to `BrowserChallengeError`, and page content return.

- [ ] **Step 2: Run eproc tests and verify RED**

  Run: `uv run --project packages/juscraper-cloud pytest tests/test_eproc.py -q`

- [ ] **Step 3: Implement the smallest selector cascade**

  Use accessible labels/roles first, then stable eproc IDs (`txtNumProcesso`, `sbmNovo`). Treat `Detalhes do Processo` plus `Capa do Processo` as success. Treat a returned search form without a captcha error as not found. Raise `BrowserChallengeError` on explicit challenge failure or timeout.

- [ ] **Step 4: Run eproc tests and verify GREEN**

  Run: `uv run --project packages/juscraper-cloud pytest tests/test_eproc.py -q`

- [ ] **Step 5: Write failing scraper/factory contract tests**

  Cover required browser/deployment, allowed deployment values, pydantic validation, single/list CNJ alignment, one-row-per-process DataFrame output, `None` rows, `sleep_time`, and upstream-factory delegation remaining unchanged.

- [ ] **Step 6: Run TRF tests and verify RED**

  Run: `uv run --project packages/juscraper-cloud pytest tests/test_trf.py -q`

- [ ] **Step 7: Implement clients and factory registration**

  Keep TRF2/TRF4 thin subclasses over one shared eproc base because there are two concrete occurrences. Do not add tribunal-name conditionals inside shared flow code.

- [ ] **Step 8: Run Task 3 tests and commit**

  Run: `uv run --project packages/juscraper-cloud pytest -q`

  Commit: `feat(cloud): adiciona fluxo eproc remoto para TRF2 e TRF4`

---

### Task 4: Vendor-neutral Documentation and Reproducible Benchmark Harness

**Files:**
- Create: `packages/juscraper-cloud/README.md`
- Create: `packages/juscraper-cloud/examples/colab_proxy_and_browser.ipynb`
- Create: `experiments/juscraper_cloud/benchmark.py`
- Create: `packages/juscraper-cloud/tests/test_benchmark_contract.py`

**Interfaces:**
- Benchmark accepts a generic proxy URL or Playwright/CDP endpoint from environment variables and writes JSON Lines containing court, deployment, CNJ hash, success, elapsed seconds, error category, and optional externally supplied cost metadata.
- It never writes CNJs, credentials, response bodies, or provider names.

- [ ] **Step 1: Write failing benchmark-contract tests**

  Verify secret/CNJ redaction, JSONL schema, deterministic hashing, 90% proxy threshold, 9/10 per-court browser threshold, and failure when any court has a systematic zero-success result.

- [ ] **Step 2: Run benchmark tests and verify RED**

  Run: `uv run --project packages/juscraper-cloud pytest tests/test_benchmark_contract.py -q`

- [ ] **Step 3: Implement the generic harness**

  Keep commercial session provisioning out of the published package. Accept a dotted provider-factory path so private experiments can construct any `BrowserProvider` implementation.

- [ ] **Step 4: Write English package documentation and Colab example**

  Document proxy execution, custom CA bundles, local Playwright, Playwright WebSocket, CDP, custom `BrowserProvider`, TRF deployment selection, privacy cautions, and rate limits. Do not name commercial services.

- [ ] **Step 5: Render/execute the notebook and run package checks**

  Run: `uv run --project packages/juscraper-cloud pytest -q`

  Run: `uv run --project packages/juscraper-cloud python -m build`

  Inspect wheel and sdist to confirm `experiments/`, credentials, and raw samples are absent.

- [ ] **Step 6: Run repository quality checks and commit**

  Run: `uv run pytest`

  Run: `uv run ruff check packages/juscraper-cloud experiments/juscraper_cloud`

  Run: `uv run mypy packages/juscraper-cloud/src`

  Commit: `docs(cloud): documenta execução remota neutra`

---

### Task 5: Final Review and Evidence

**Files:**
- Modify only files required by review findings.

- [ ] **Step 1: Run the complete companion-package suite and build**

  Run: `uv run --project packages/juscraper-cloud pytest -q`

  Run: `uv run --project packages/juscraper-cloud python -m build`

- [ ] **Step 2: Run the complete upstream offline suite**

  Run: `uv run pytest`

- [ ] **Step 3: Run static gates**

  Run: `uv run ruff check packages/juscraper-cloud experiments/juscraper_cloud`

  Run: `uv run mypy packages/juscraper-cloud/src`

- [ ] **Step 4: Inspect package contents and git diff**

  Confirm no credentials, raw judicial responses, provider names in published docs/API, or changes to upstream `src/juscraper` public behavior.

- [ ] **Step 5: Request whole-branch review and address findings**

  Generate a review package from the fork/main merge base, dispatch a final reviewer, fix all Critical/Important findings, and rerun every covering test.

- [ ] **Step 6: Commit final fixes**

  Commit subject and body must be in Portuguese.
