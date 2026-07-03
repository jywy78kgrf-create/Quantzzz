/**
 * Chain-truth reconciliation for the paid-probe ledger.
 *
 * The executor's in-run "settled" detection relied on the X-PAYMENT-RESPONSE
 * header. Several endpoints settle the payment ON-CHAIN but return no such
 * header (some 200 with a success body, some 400/500 after charging). Those
 * were recorded settled=$0, so the settled-only skip-set re-charged 4 of them
 * on run 2 — a "one payment per endpoint" violation. This script rebuilds
 * settlement truth from chain and rewrites the ledger's settled_usdc_onchain /
 * settled_onchain fields accordingly, and writes a chain-settled endpoint set
 * that the executor now uses for its skip logic (so a re-run cannot double-pay).
 *
 * Read-only against chain; rewrites only our own ledger + a derived set file.
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const REPO = path.resolve(HERE, "..", "..");
const OUT_DIR = path.join(REPO, "data", "raw", "paid_probes", "2026-07-03");
const RESULTS = path.join(OUT_DIR, "results.jsonl");
const SETTLED_SET = path.join(OUT_DIR, "chain_settled_paytos.json");
const SAMPLE = path.join(REPO, "data", "processed", "paid_probe_sample.csv");
const WALLET = "0xE5E6BD49d520410D297161F77b05D84A2a768242";
const USDC = "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913";

async function outboundTransfers() {
  let params = new URLSearchParams({ token: USDC, filter: "from", type: "ERC-20" });
  const items = [];
  for (let i = 0; i < 10; i++) {
    const r = await fetch(
      `https://base.blockscout.com/api/v2/addresses/${WALLET}/token-transfers?${params}`,
      { headers: { "User-Agent": "x402-endpoint-quality-audit/0.1" } }).then((x) => x.json());
    items.push(...(r.items ?? []));
    if (!r.next_page_params) break;
    params = new URLSearchParams({ token: USDC, filter: "from", type: "ERC-20",
      ...r.next_page_params });
  }
  return items;
}

const sample = Object.fromEntries(
  fs.readFileSync(SAMPLE, "utf8").trim().split("\n").slice(1).map((l) => {
    const v = l.split(",");
    return [v[3].toLowerCase(), v[1]]; // pay_to -> url
  }));

const xfers = await outboundTransfers();
const byPayto = {};
for (const it of xfers) {
  const to = it.to.hash.toLowerCase();
  (byPayto[to] ??= []).push({
    tx: it.transaction_hash.toLowerCase(),
    usdc: Number(it.total.value) / 1e6, ts: it.timestamp });
}

// URL -> total settled on-chain, count of settlements
const urlSettled = {};
for (const [to, txs] of Object.entries(byPayto)) {
  const url = sample[to];
  if (!url) continue;
  urlSettled[url] = { count: txs.length, usdc: txs.reduce((s, t) => s + t.usdc, 0),
                      txs: txs.map((t) => t.tx) };
}

// rewrite ledger: mark chain-settled truth
const rows = fs.readFileSync(RESULTS, "utf8").trim().split("\n").map((l) => JSON.parse(l));
for (const r of rows) {
  const s = urlSettled[r.url];
  r.settled_onchain = Boolean(s);
  if (s && !r.payment_response) {
    // header-less settlement the executor missed: annotate, don't fabricate a
    // per-attempt amount (can't split multi-attempt), flag for scoring
    r.settled_onchain_headerless = true;
  }
}
fs.writeFileSync(RESULTS, rows.map((r) => JSON.stringify(r)).join("\n") + "\n");

// chain-settled payTo set for the executor skip logic
const settledPaytos = Object.keys(byPayto).filter((to) => sample[to]);
fs.writeFileSync(SETTLED_SET, JSON.stringify({
  generated_note: "payTo wallets that received USDC from the burner; used as the "
    + "chain-truth skip-set so re-runs cannot double-pay a headerless settler",
  wallet: WALLET,
  settled_paytos: settledPaytos,
  settled_urls: Object.keys(urlSettled),
}, null, 1));

const totalOut = xfers.reduce((s, it) => s + Number(it.total.value) / 1e6, 0);
const doubles = Object.entries(urlSettled).filter(([, s]) => s.count > 1);
console.log(`on-chain outbound total: $${totalOut.toFixed(4)} (${xfers.length} transfers)`);
console.log(`endpoints settled on-chain: ${Object.keys(urlSettled).length}`);
console.log(`double-charged endpoints: ${doubles.length}`);
for (const [u, s] of doubles) console.log(`  ${s.count}x $${s.usdc.toFixed(3)} ${u}`);
console.log(`wrote chain-settled set: ${path.relative(REPO, SETTLED_SET)}`);
