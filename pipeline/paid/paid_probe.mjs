/**
 * Phase 2.5 paid delivery verification — mystery shopper executor.
 *
 * Safety gates (ALL must hold before any payment):
 *   1. --confirm flag on the command line (the user's explicit go)
 *   2. X402_AUDIT_WALLET_KEY present in env (never read from argv, never logged)
 *   3. per-endpoint price cap ($1.00), enforced from OUR sample file AND as
 *      maxValue passed to the x402 client (protects against a server quoting
 *      more than its listing)
 *   4. cumulative spend halt at $45, hard budget $50
 *   5. one payment attempt per endpoint, ever (ledger in raw output dir;
 *      re-runs skip endpoints already attempted)
 *
 * Raw results (status, headers incl. X-PAYMENT-RESPONSE, body <=64KB) are
 * appended to data/raw/paid_probes/<label>/results.jsonl — committed.
 * Wallet key and payment signatures are NEVER written to disk.
 *
 * Usage:  node paid_probe.mjs            # dry run: prints plan, pays nothing
 *         node paid_probe.mjs --confirm  # executes payments per the plan
 */

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { privateKeyToAccount } from "viem/accounts";
import { wrapFetchWithPayment } from "x402-fetch";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const REPO = path.resolve(HERE, "..", "..");
const SAMPLE = path.join(REPO, "data", "processed", "paid_probe_sample.csv");
const BAZAAR_RAW_DIR = path.join(REPO, "data", "raw", "bazaar", "2026-07-03");
const OUT_DIR = path.join(REPO, "data", "raw", "paid_probes", "2026-07-03");
const RESULTS = path.join(OUT_DIR, "results.jsonl");

const PER_ENDPOINT_CAP_USDC = 1.0;
const HALT_AT_USDC = 45.0;
const BUDGET_CAP_USDC = 50.0;
const MAX_BODY = 65536;
const TIMEOUT_MS = 30000;
const UA = "x402-endpoint-quality-audit/0.1 (paid delivery verification pilot; one payment per endpoint)";

const confirm = process.argv.includes("--confirm");

function readCsv(file) {
  const [head, ...lines] = fs.readFileSync(file, "utf8").trim().split("\n");
  const cols = head.split(",");
  return lines.map((l) => {
    // sample file has no quoted commas (URLs are unquoted but comma-free)
    const vals = l.split(",");
    return Object.fromEntries(cols.map((c, i) => [c, vals[i]]));
  });
}

/** Example request bodies for POST routes, from the Bazaar catalog metadata. */
function loadExampleInputs() {
  const zlib = require_zlib();
  const map = new Map();
  for (const f of fs.readdirSync(BAZAAR_RAW_DIR).filter((f) => f.endsWith(".json.gz"))) {
    const body = JSON.parse(
      zlib.gunzipSync(fs.readFileSync(path.join(BAZAAR_RAW_DIR, f))).toString());
    for (const it of body.items ?? []) {
      const info = it?.extensions?.bazaar?.info;
      if (info?.input) map.set(it.resource, info.input);
    }
  }
  return map;
}
import zlib from "node:zlib";
function require_zlib() { return zlib; }

function appendResult(rec) {
  fs.mkdirSync(OUT_DIR, { recursive: true });
  fs.appendFileSync(RESULTS, JSON.stringify(rec) + "\n");
}

function attempted() {
  if (!fs.existsSync(RESULTS)) return new Set();
  return new Set(fs.readFileSync(RESULTS, "utf8").trim().split("\n")
    .filter(Boolean).map((l) => JSON.parse(l).url));
}

async function main() {
  const sample = readCsv(SAMPLE);
  const done = attempted();
  const todo = sample.filter((r) => !done.has(r.url));
  const projected = todo.reduce((s, r) => s + Number(r.price_usdc), 0);

  console.log(`sample=${sample.length} attempted=${done.size} todo=${todo.length}`);
  console.log(`projected spend this run: $${projected.toFixed(2)} ` +
              `(caps: $${PER_ENDPOINT_CAP_USDC}/endpoint, halt $${HALT_AT_USDC}, budget $${BUDGET_CAP_USDC})`);
  if (!confirm) {
    console.log("\nDRY RUN — no payments. Re-run with --confirm to execute.");
    for (const r of todo.slice(0, 5)) console.log(`  ${r.stratum}  $${r.price_usdc}  ${r.url}`);
    if (todo.length > 5) console.log(`  … ${todo.length - 5} more (data/processed/paid_probe_sample.csv)`);
    return;
  }

  const key = process.env.X402_AUDIT_WALLET_KEY;
  if (!key) throw new Error("X402_AUDIT_WALLET_KEY not set — aborting before any payment.");
  const account = privateKeyToAccount(key);
  console.log(`paying from burner: ${account.address}`);

  // CRITICAL: maxValue is the THIRD positional arg (a BigInt), NOT a config
  // object. Passing {maxValue:...} here silently disables the cap — the
  // library compares BigInt > object (always false) and also loses its own
  // 0.1-USDC default. This bug let a $15 charge through on the first run
  // (listed $0.01). Correct call:
  const fetchWithPay = wrapFetchWithPayment(
    fetch, account, BigInt(Math.round(PER_ENDPOINT_CAP_USDC * 1e6)));
  const examples = loadExampleInputs();

  let spent = done.size
    ? [...fs.readFileSync(RESULTS, "utf8").trim().split("\n")]
        .filter(Boolean).map((l) => JSON.parse(l))
        .reduce((s, r) => s + (r.paid_usdc ?? 0), 0)
    : 0;
  console.log(`already spent (ledger): $${spent.toFixed(2)}`);

  for (const [i, row] of todo.entries()) {
    const price = Number(row.price_usdc);
    if (price > PER_ENDPOINT_CAP_USDC) {
      appendResult({ url: row.url, stratum: row.stratum, ts: new Date().toISOString(),
                     outcome: "SKIPPED_PRICE_CAP", listed_price_usdc: price, paid_usdc: 0 });
      continue;
    }
    if (spent + price > HALT_AT_USDC) {
      console.log(`HALT: spent $${spent.toFixed(2)} + next $${price} would cross $${HALT_AT_USDC}`);
      break;
    }

    const ex = examples.get(row.url);
    const method = ex?.method && ["POST", "PUT", "PATCH"].includes(ex.method) ? ex.method : "GET";
    // substitute path params from the example, if the route template has any
    let url = row.url;
    if (ex?.pathParams) {
      for (const [k, v] of Object.entries(ex.pathParams)) {
        url = url.replace(`:${k}`, encodeURIComponent(String(v)));
      }
    }
    const init = {
      method,
      headers: { "User-Agent": UA, Accept: "application/json" },
      signal: AbortSignal.timeout(TIMEOUT_MS),
    };
    if (method !== "GET" && ex?.body !== undefined) {
      init.headers["Content-Type"] = "application/json";
      init.body = JSON.stringify(ex.body);
    }

    const rec = {
      url: row.url, request_url: url, stratum: row.stratum, method,
      listed_price_usdc: price, ts: new Date().toISOString(),
      paid_usdc: 0, outcome: null, status: null, payment_response: null,
      tx_hash: null, settle_network: null, content_type: null,
      body_b64: null, body_sha256: null, body_bytes_total: null, error: null,
    };
    try {
      const resp = await fetchWithPay(url, init);
      rec.status = resp.status;
      rec.content_type = resp.headers.get("content-type");
      rec.payment_response = resp.headers.get("x-payment-response");
      // Untrusted body: captured as inert base64 bytes (64KB cap) + hash.
      // Never parsed, rendered, or executed here; scoring decodes in
      // isolation afterward.
      const buf = Buffer.from(await resp.arrayBuffer());
      rec.body_bytes_total = buf.length;
      rec.body_b64 = buf.subarray(0, MAX_BODY).toString("base64");
      rec.body_sha256 = (await import("node:crypto")).createHash("sha256")
        .update(buf).digest("hex");
      // Settle header (facilitator-produced, seller-relayed): decode the
      // base64 JSON defensively to surface the on-chain tx hash explicitly.
      if (rec.payment_response) {
        try {
          const settle = JSON.parse(
            Buffer.from(rec.payment_response, "base64").toString("utf8"));
          rec.tx_hash = settle?.transaction ?? null;
          rec.settle_network = settle?.network ?? null;
        } catch { /* raw header is still committed verbatim */ }
      }
      // x402-fetch only returns non-402 after settling payment (or if the
      // route turned out to be free); a settle header marks money moved.
      if (rec.payment_response) {
        rec.paid_usdc = price;
        spent += price;
        rec.outcome = resp.ok ? "PAID_2XX" : "PAID_NON2XX";
      } else {
        rec.outcome = `NO_PAYMENT_HTTP_${resp.status}`;
      }
    } catch (err) {
      rec.error = String(err?.message ?? err).slice(0, 400);
      // x402-fetch throws after payment failure or pre-payment errors; it
      // does not retry, and neither do we (one attempt per endpoint).
      rec.outcome = /payment/i.test(rec.error) ? "PAYMENT_FAILED" : "REQUEST_FAILED";
    }
    appendResult(rec);
    console.log(`[${i + 1}/${todo.length}] ${rec.outcome} $${rec.paid_usdc} ` +
                `cum=$${spent.toFixed(2)} ${row.url.slice(0, 70)}`);
    await new Promise((r) => setTimeout(r, 1500)); // pacing
  }
  console.log(`DONE. total spent (ledger): $${spent.toFixed(2)}`);
}

main().catch((e) => { console.error("FATAL:", e.message); process.exit(1); });
