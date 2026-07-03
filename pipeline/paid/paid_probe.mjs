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
const haltArg = process.argv.find((a) => a.startsWith("--halt="));
const HALT_USDC = haltArg ? Number(haltArg.split("=")[1]) : HALT_AT_USDC;
const dryrun402 = process.argv.find((a) => a.startsWith("--dryrun-402="));

/**
 * CAIP-2 -> SDK network-name normalization (Step 2b).
 * x402-fetch 1.2.0's PaymentRequirementsSchema rejects CAIP-2 chain ids
 * ("eip155:8453"), which x402 v2 servers legitimately send — that blocked 30
 * of 75 payments in run 1 (report finding). This wrapper rewrites the network
 * field of 402 payment-requirement bodies to the SDK's names before the SDK
 * parses them. Mainnet-Base only: testnets stay unmapped (and thus unpayable).
 */
const CAIP2_MAP = {
  "eip155:8453": "base",
  "solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp": "solana",
};
function normalizeAccept(a, url) {
  let changed = false;
  if (CAIP2_MAP[a?.network]) { a.network = CAIP2_MAP[a.network]; changed = true; }
  // v2 field names -> v1 names the SDK schema requires
  if (a.maxAmountRequired === undefined && a.amount !== undefined) {
    a.maxAmountRequired = String(a.amount); changed = true;
  }
  for (const [k, v] of Object.entries(
      { resource: url, description: "", mimeType: "" })) {
    if (a[k] === undefined) { a[k] = v; changed = true; }
  }
  return changed;
}
function normalizingFetch(baseFetch) {
  return async (url, init) => {
    const resp = await baseFetch(url, init);
    if (resp.status !== 402) return resp;
    let body;
    try { body = await resp.clone().json(); } catch { return resp; }
    if (!Array.isArray(body?.accepts)) return resp;
    let changed = false;
    for (const a of body.accepts) {
      if (normalizeAccept(a, String(url))) changed = true;
    }
    if (!changed) return resp;
    return new Response(JSON.stringify(body), {
      status: resp.status, statusText: resp.statusText, headers: resp.headers,
    });
  };
}

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

function ledgerRecords() {
  if (!fs.existsSync(RESULTS)) return [];
  return fs.readFileSync(RESULTS, "utf8").trim().split("\n")
    .filter(Boolean).map((l) => JSON.parse(l));
}

/** Endpoints with a prior SETTLEMENT are permanently skipped (one payment
 *  per endpoint, ever). Settlement truth comes from CHAIN, not the response
 *  header: run-1/2 exposed endpoints that charge on-chain yet return no
 *  X-PAYMENT-RESPONSE header (some 200, some 400/500), which a header-only
 *  skip-set re-charged. reconcile_chain.mjs writes chain_settled_paytos.json;
 *  we union it with header-detected settlements and body-embedded tx claims. */
const SETTLED_SET = path.join(OUT_DIR, "chain_settled_paytos.json");
function settledUrls() {
  const set = new Set(ledgerRecords()
    .filter((r) => r.payment_response || (r.settled_usdc_onchain ?? 0) > 0
      || r.settled_onchain === true)
    .map((r) => r.url));
  if (fs.existsSync(SETTLED_SET)) {
    for (const u of JSON.parse(fs.readFileSync(SETTLED_SET, "utf8")).settled_urls ?? [])
      set.add(u);
  }
  return set;
}

/** Step 2c: settled amount from the on-chain tx receipt, DURING the run.
 *  Parses USDC Transfer logs where `from` topic == our wallet. Returns
 *  {usdc, verified}; on persistent RPC failure assumes the per-endpoint cap
 *  for halt accounting and flags the record unverified. */
const USDC_ADDR = "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913";
const TRANSFER_TOPIC =
  "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"; // ERC-20 Transfer event topic (public constant, not-a-key)
async function settledFromReceipt(txHash, wallet) {
  for (let i = 0; i < 6; i++) {
    try {
      const r = await fetch("https://mainnet.base.org", {
        method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify({ jsonrpc: "2.0", id: 1,
          method: "eth_getTransactionReceipt", params: [txHash] }),
        signal: AbortSignal.timeout(15000),
      }).then((x) => x.json());
      const rcpt = r?.result;
      if (rcpt) {
        let units = 0n;
        for (const log of rcpt.logs ?? []) {
          if (log.address?.toLowerCase() === USDC_ADDR
              && log.topics?.[0] === TRANSFER_TOPIC
              && log.topics?.[1]?.slice(-40).toLowerCase()
                 === wallet.slice(2).toLowerCase()) {
            units += BigInt(log.data);
          }
        }
        return { usdc: Number(units) / 1e6, verified: true };
      }
    } catch { /* retry */ }
    await new Promise((res) => setTimeout(res, 2000 * (i + 1)));
  }
  return { usdc: PER_ENDPOINT_CAP_USDC, verified: false }; // conservative
}

async function main() {
  if (dryrun402) {
    // Step 2b verification: fetch a real 402, normalize CAIP-2, parse with
    // the SDK schema, apply the cap — and STOP. No signing, no payment.
    const url = dryrun402.split("=").slice(1).join("=");
    const nf = normalizingFetch(fetch);
    const resp = await nf(url, { headers: { "User-Agent": UA },
                                 signal: AbortSignal.timeout(TIMEOUT_MS) });
    console.log(`dryrun-402 ${url} -> HTTP ${resp.status}`);
    if (resp.status !== 402) return;
    const body = await resp.json();
    const { PaymentRequirementsSchema } = await import("x402/types");
    const parsed = body.accepts.map((a) => PaymentRequirementsSchema.parse(a));
    const usdc = Number(parsed[0].maxAmountRequired) / 1e6;
    console.log(`parsed OK: network=${parsed[0].network} amount=$${usdc} ` +
                `payTo=${parsed[0].payTo}`);
    console.log(usdc <= PER_ENDPOINT_CAP_USDC
      ? `cap check: $${usdc} <= $${PER_ENDPOINT_CAP_USDC} — would proceed`
      : `cap check: $${usdc} > $${PER_ENDPOINT_CAP_USDC} — would THROW`);
    console.log("dry run: stopping before payment construction.");
    return;
  }

  const sample = readCsv(SAMPLE);
  const done = settledUrls();
  const todo = sample.filter((r) => !done.has(r.url));
  const projected = todo.reduce((s, r) => s + Number(r.price_usdc), 0);

  console.log(`sample=${sample.length} settled-prior=${done.size} todo=${todo.length}`);
  console.log(`projected spend this run: $${projected.toFixed(2)} ` +
              `(caps: $${PER_ENDPOINT_CAP_USDC}/endpoint, halt $${HALT_USDC}, budget $${BUDGET_CAP_USDC})`);
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
  // (listed $0.01). Correct call (verified by test_cap.mjs):
  const fetchWithPay = wrapFetchWithPayment(
    normalizingFetch(fetch), account,
    BigInt(Math.round(PER_ENDPOINT_CAP_USDC * 1e6)));
  const examples = loadExampleInputs();

  // Cumulative halt accounting uses on-chain SETTLED amounts (receipt-
  // verified during the run), never listed prices. Run 1's amounts were
  // reconciled post-hoc and live in settled_usdc_onchain.
  let spent = 0; // this-run settled total (halt basis per Step 3)
  console.log(`prior settled (all runs, ledger): $${
    ledgerRecords().reduce((s, r) => s + (r.settled_usdc_onchain ?? 0), 0)
      .toFixed(2)}`);

  for (const [i, row] of todo.entries()) {
    const price = Number(row.price_usdc);
    if (price > PER_ENDPOINT_CAP_USDC) {
      appendResult({ url: row.url, stratum: row.stratum, ts: new Date().toISOString(),
                     outcome: "SKIPPED_PRICE_CAP", listed_price_usdc: price, settled_usdc_onchain: 0 });
      continue;
    }
    // Halt guard uses SETTLED amounts; next-payment exposure is the per-
    // endpoint CAP (not the listed price — run 1 proved listings can lie).
    if (spent + PER_ENDPOINT_CAP_USDC > HALT_USDC) {
      console.log(`HALT: settled $${spent.toFixed(2)} + cap $${PER_ENDPOINT_CAP_USDC} would cross $${HALT_USDC}`);
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
      settled_usdc_onchain: 0, receipt_verified: null, overcharged: false,
      outcome: null, status: null, payment_response: null,
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
      // Step 2c: verify the settled amount from the tx receipt NOW, and
      // account the halt off that on-chain number.
      if (rec.payment_response) {
        if (rec.tx_hash) {
          const settled = await settledFromReceipt(rec.tx_hash, account.address);
          rec.settled_usdc_onchain = settled.usdc;
          rec.receipt_verified = settled.verified;
        } else {
          rec.settled_usdc_onchain = PER_ENDPOINT_CAP_USDC; // conservative
          rec.receipt_verified = false;
        }
        rec.overcharged = rec.settled_usdc_onchain > price + 1e-9;
        spent += rec.settled_usdc_onchain;
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
    console.log(`[${i + 1}/${todo.length}] ${rec.outcome} $${rec.settled_usdc_onchain} ` +
                `cum=$${spent.toFixed(2)} ${row.url.slice(0, 70)}`);
    await new Promise((r) => setTimeout(r, 1500)); // pacing
  }
  console.log(`DONE. total spent (ledger): $${spent.toFixed(2)}`);
}

main().catch((e) => { console.error("FATAL:", e.message); process.exit(1); });
