# juscraper-cloud

`juscraper-cloud` is a vendor-neutral companion package for `juscraper`. It adds two opt-in transport paths without
changing the upstream factory:

- a whole-session HTTP(S) proxy for existing request-based scrapers; and
- local or remote Playwright pages for the browser-only TRF2 and TRF4 clients.

The package does not provision remote sessions, store credentials, or silently fall back to direct networking. You supply
and operate the network or browser endpoint.

## Install

```bash
python -m pip install juscraper-cloud
```

Install the browser extra when using any Playwright provider:

```bash
python -m pip install "juscraper-cloud[browser]"
playwright install chromium
```

## Run an existing scraper through a proxy

Configure a generic HTTP or HTTPS proxy URL. Credentials may be included in the URL, but keep the variable in a secret
store and never print it.

```bash
export JUSCRAPER_PROXY_URL='https://proxy.example:8443'
```

```python
from juscraper_cloud import scraper

client = scraper("tjsp")
result = client.cjsg("public procurement", paginas=range(1, 2))
```

The route replaces all existing session proxy entries, disables environment-proxy merging for that session, and applies to
both HTTP and HTTPS requests. If the configured route fails, the request fails; it is never retried directly.

You can also configure the route explicitly:

```python
from juscraper_cloud import ProxyRoute, scraper

route = ProxyRoute("https://proxy.example:8443")
client = scraper("tjsp", route=route)
```

### Custom certificate authority

Never disable TLS verification. Point the route to a PEM certificate bundle instead:

```bash
export JUSCRAPER_PROXY_CA_BUNDLE='/content/private/ca-bundle.pem'
```

Or pass it explicitly:

```python
route = ProxyRoute(
    "https://proxy.example:8443",
    ca_bundle="/content/private/ca-bundle.pem",
)
```

## Browser providers

Every provider exposes a managed `open_page()` context. The provider releases the resources it owns on normal and
exceptional exits.

### Local Playwright

```python
from juscraper_cloud import LocalPlaywrightProvider

browser = LocalPlaywrightProvider(headless=True)
```

A local browser can itself use a proxy:

```python
browser = LocalPlaywrightProvider(
    headless=True,
    proxy_server="https://proxy.example:8443",
)
```

### Playwright WebSocket

```python
from juscraper_cloud import PlaywrightWsProvider

browser = PlaywrightWsProvider(
    endpoint="wss://browser.example/playwright",
    headers={"Authorization": "Bearer " + secret_token},
)
```

### Chrome DevTools Protocol

```python
from juscraper_cloud import CdpPlaywrightProvider

browser = CdpPlaywrightProvider(
    endpoint="wss://browser.example/cdp",
    headers={"Authorization": "Bearer " + secret_token},
)
```

Use the WebSocket provider only for a Playwright protocol endpoint. Use `CdpPlaywrightProvider` for a CDP endpoint.

### Custom `BrowserProvider`

Private infrastructure can implement the small public protocol without becoming a package dependency:

```python
from contextlib import contextmanager


class ResearchBrowserProvider:
    @contextmanager
    def open_page(self):
        page, close = open_private_managed_page()
        try:
            yield page
        finally:
            close()
```

`open_page()` must yield a synchronous Playwright-compatible page and close every resource owned by the implementation.
Do not put provisioning code, endpoint credentials, or infrastructure names in published notebooks or result files.

## TRF2 and TRF4 deployment selection

Browser clients require an explicit deployment:

| Court | Deployment values |
| --- | --- |
| `trf2` | `rj`, `es` |
| `trf4` | `pr`, `sc`, `rs` |

```python
from juscraper_cloud import LocalPlaywrightProvider, scraper

browser = LocalPlaywrightProvider(headless=True)
client = scraper("trf2", browser=browser, deployment="rj", sleep_time=1.0)
frame = client.cpopg(cnj_from_private_input)
```

The TRF clients do not accept `ProxyRoute`; configure a browser provider instead.

## Reproducible benchmark

The benchmark harness lives under `experiments/juscraper_cloud/` in the source repository and is intentionally excluded
from the published distribution. Its private input is JSON Lines with `court`, `deployment`, and `cnj`. Use `proxy` as the
deployment for request-based proxy cases; use one of the court deployments above for browser cases.

Set a private HMAC key before running it:

```bash
export JUSCRAPER_BENCHMARK_HASH_KEY='a-long-random-research-secret'
python experiments/juscraper_cloud/benchmark.py \
  --cases /content/private/cases.jsonl \
  --output /content/results.jsonl
```

Browser configuration is selected from exactly one of these variables:

- `JUSCRAPER_BROWSER_WS_ENDPOINT`
- `JUSCRAPER_BROWSER_CDP_ENDPOINT`
- `JUSCRAPER_BROWSER_PROVIDER_FACTORY`, a dotted zero-argument callable path for a private `BrowserProvider`

Optional authentication headers are read from `JUSCRAPER_BROWSER_HEADERS_JSON`. Optional externally measured numeric cost
fields are read from `JUSCRAPER_BENCHMARK_COST_JSON`. Its public numeric keys are `request_cost`, `billable_seconds`, and
`units`; arbitrary keys and all string values are rejected.

Cases run sequentially with a one-second delay between them. `JUSCRAPER_BENCHMARK_DELAY_SECONDS` may increase that delay;
values below `1.0` are rejected. This pacing is applied by the harness because each benchmark case creates its own client.

Each output row contains only `court`, `deployment`, `cnj_hash`, `success`, `elapsed_seconds`, `error_category`, and optional
numeric `cost_metadata`. The harness never serializes raw CNJs, endpoint credentials, provider names, exception messages, or
response bodies. Court/deployment values are validated against the package's public court matrix before the output file is
opened. The gate requires a proxy cohort with at least ten observations and 90% aggregate success. It also requires both
browser court cohorts (TRF2 and TRF4), each with at least ten observations and 90% success aggregated across any mix of that
court's deployments. Every represented proxy court and required browser court must have at least one success.

## Privacy and responsible use

- Keep raw CNJs, credentials, browser headers, proxy URLs, and response bodies in private storage.
- Publish only the benchmark JSONL with keyed hashes. Store the HMAC key separately from published results.
- Review judicial data for personal and sensitive information before any disclosure.
- Never add raw responses, screenshots, credentials, or private input files to source control.
- Keep `sleep_time >= 1.0`, run requests sequentially, start with a small sample, and respect court availability and usage
  limits. Remote execution does not justify aggressive concurrency.

The executable notebook walkthrough is in
[`examples/colab_proxy_and_browser.ipynb`](examples/colab_proxy_and_browser.ipynb).
