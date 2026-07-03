# Hand Inspection — 5 Seeded-Random Sellers per Final Bucket

Evidence: `analysis/hand_inspection_evidence.json` (regenerable via
`analysis/hand_inspection_sample.py`, seed namespace "hand-inspection",
seed 402402). Verdict = does the raw transfer pattern match the bucket
definition? Written 2026-07-03 after the facilitator-inflation correction.

## ACTIVE_LEGITIMATE (defined: ≥20 tx, ≥5 recomputed buyers, active ≤30d)
| Seller | Evidence | Verdict |
|---|---|---|
| 6x5ocVNEwuBpi2Gs… | 155 tx, 8 payers, top2 66%, Mar→Jun 2026, 10d silent | MATCHES — sustained multi-buyer service; concentration below rig thresholds |
| 2ny4T8BbY6hveW8o… | 106 tx, 66 payers, top2 10%, active | MATCHES — diverse payers, live |
| 2Vgb83uPkms6Jzfd… | 1,182 tx, 122 payers, 6-month span, 1d silent | MATCHES — textbook operating service |
| 0x21dfc81726538f… | 706 tx, 47 payers, uniform $0.01 price, 8-month span, 9d | MATCHES — fixed-price API; shows why uniform amounts alone must not imply TEST_RIG |
| 4ShLAGjk8mTYMCmX… | 34 tx, 26 payers, recent | MATCHES — small but real and diverse |

## TEST_RIG (self-deal ≥10% vol, or ≤2 buyers, or top-2 ≥90% vol)
| Seller | Evidence | Verdict |
|---|---|---|
| 0x9467452cd38444… | 5 tx, 1 payer, one day | MATCHES — single-payer probe |
| B8xn1BeMGEyoqtmZ… | 10 tx, 1 payer, one day | MATCHES |
| 0x4668dfcabb79ed… | 67 tx, 1 payer over 3 weeks | MATCHES — one wallet exercising an endpoint |
| 0x150d29e1ac79b7… | 8 tx, 1 payer | MATCHES |
| 0x1b4ee66224aa14… | 52 tx, 1 payer over 5 weeks | MATCHES |

## GHOST (<5 lifetime tx)
| Seller | Evidence | Verdict |
|---|---|---|
| 0x6f318185c58596… | 2 tx, 1 payer, one day | MATCHES |
| 9NCwwrEb5M7qPKNb… | 1 tx | MATCHES |
| 0x45abdcb647a9e2… | 1 tx | MATCHES |
| 0x8259f9c1e4a47a… | 1 tx | MATCHES |
| GzVoPrZuYdH1DbYJ… | 1 tx ($0.0001) | MATCHES |

## DORMANT (real history, >60d silent)
| Seller | Evidence | Verdict |
|---|---|---|
| 0x69020c0ff44b26… | 103 tx, 6 payers, **48% self-pay**, 106d silent | DORMANT holds (>60d silent), but pattern is rig-like; census-only seller — consistent with the measured census under-detection direction (control: 19% of census-DORMANT reclassify under deep signals) |
| BHPiXHHKRFZnJSCu… | 67 tx, 46 payers, single-day event, 101d silent | MATCHES — one-day usage spike, then gone |
| 9dVdnqJQ8Gwudv68… | 296 tx, 215 payers, single day, 116d silent | MATCHES (mint-day-shaped but <1,000 tx, below MEMECOIN floor) |
| 4MfkFeLWDaRoRPSe… | 59 tx, 44 payers, 2 days, 100d silent | MATCHES |
| 8EnGZpNczNRkzRs5… | 44 tx, 32 payers, 2 days, 93d silent | MATCHES |

## MEMECOIN (mass identical small payments, then silence)
| Seller | Evidence | Verdict |
|---|---|---|
| HPPuic3YjSDZvxNv… | 7.2k tx, 721 payers, $0.05 × 98.6%, single day, 153d silent | MATCHES |
| 8ZF4fB1RH947hECu… | 6.4k tx, 735 payers, $0.05 × 98.3%, single day | MATCHES |
| 7vhcwvqiYUi8VrNp… | 801k tx, $0.01 uniform, 25-day span, 125d silent | MATCHES (sustained-mint rule) |
| 0x089883de0b1af1… | 11.1k tx, 1,293 payers, $1.00 uniform, 3 days (Oct-2025 wave), 246d silent | MATCHES |
| 0x9b4dc4f56ec94e… | 121k tx, $1.00 uniform, single day, 249d silent | MATCHES |

## DUPLICATE (shares endpoint URL with a higher-volume wallet)
| Seller | Evidence | Verdict |
|---|---|---|
| 0xe1df6968935328… | 565 tx, 168 payers, modal $100, silent 234d | MATCHES definition (URL shared); activity itself real-but-dormant — bucket priority puts URL-duplication first |
| 0x4b6f4a2f7c9954… | 54 tx, 47 payers, $1 uniform single day | MATCHES definition (URL shared) |
| 0x3801cd9bce3130… | 48k tx, 4 payers in sample, top2 68% | MATCHES — alternate wallet of a bigger origin |
| TW6ntaGzvj63ZgPj… | 115 tx, 3 payers, **top2 97%**, active | DUPLICATE holds by URL-map, but pattern is rig-like; census-only seller (deep rule would say TEST_RIG). Known limitation, counted in control error |
| 0xb7a6a9344fe545… | 17.8k tx, 38 payers, silent 329d | MATCHES definition (URL shared) |

## LOW_ACTIVITY (residual: recent multi-buyer, below sustained bar)
| Seller | Evidence | Verdict |
|---|---|---|
| 8hQzXhkAfXDQagFA… | 318 tx, 116 payers, 4-day window, 50d silent | MATCHES rules (50d < 60d dormancy line); drifting toward DORMANT |
| BN3UiNeewWFhnTcq… | 16 tx, 12 payers, recent | MATCHES — below 20-tx sustained bar |
| 0x7d9d1821d15b9e… | 67.8k tx, 261+ payers, 12-month span, 51d silent | MATCHES rules — large real service gone quiet inside the dormancy window; will be DORMANT in 9 days without new activity |
| XZumzDMSZK7dK3kK… | 9 tx, 4 payers, recent | MATCHES — below both bars |
| 4rPBAE4kUPEqXQ9s… | 328 tx, 207 payers, 2-day window, 47d silent | MATCHES rules; same shape as row 1 |

## Summary
33/35 verdicts match their bucket definition outright. The 2 exceptions
(1 DORMANT, 1 DUPLICATE) are census-only sellers whose ad-hoc-pulled patterns
look TEST_RIG-like — the exact under-detection direction the control sample
quantifies (census classifier error rate 1.1% overall; 19% within
census-DORMANT). No inspected seller contradicts the deep-signal rules.
