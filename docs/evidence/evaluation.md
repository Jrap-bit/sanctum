# Sanctum Evaluation Report (§9.10)

- **Run Date:** 2026-11-08T19:35:49.753583+00:00
- **Host Platform:** Darwin 27.2.0 (arm64)
- **Python Version:** 3.13.16

## Model Digests

- **qwen3:4b:** `359d7dd4bcdab3d86b87d73ac27966f4dbb9f5efdfcc75d34a8764a09474fae7`
- **qwen3:1.7b:** `8f68893c685c3ddff2aa3fffce2aa60a30bb2da65ca488b61fff134a4d1730e7`
- **llama3.2:3b:** `a80c4f17acd55265feec403c7aef86be0c25983ab279d83f3bcd3abbcb5b8b72`
- **gemma4:e2b:** `45d11505b91d888e353859f5deeeeff3ffc9b3aa42263c00904120c53851ef96`

## OCR Evaluation

| Page ID | Variant | Latency (s) | Raw CER | Norm CER | Raw WER | Norm WER | Status |
|---|---|---|---|---|---|---|---|
| ocr_page_1 | large_clean | 0.2277 | 0.0133 | 0.0133 | 0.0339 | 0.0339 | pass |
| ocr_page_2 | large_clean | 0.1817 | 0.0047 | 0.0047 | 0.0169 | 0.0169 | pass |
| ocr_page_3 | large_clean | 0.1821 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | pass |
| ocr_page_4 | noisy_rotated | 0.2041 | 0.0153 | 0.0153 | 0.1207 | 0.1207 | pass |
| ocr_page_5 | noisy_rotated | 0.2028 | 0.0092 | 0.0092 | 0.1071 | 0.1071 | pass |
| ocr_page_6 | small_font | 0.1553 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | pass |

### OCR Summary (Median)

| Metric | Value |
|---|---|
| Median Latency | 0.1925s |
| Median Raw CER | 0.0069 |
| Median Norm CER | 0.0069 |
| Median Raw WER | 0.0254 |
| Median Norm WER | 0.0254 |
| Page Coverage | 100.0% (6/6) |

### Handwritten OCR

handwritten: not measured

## LLM Evaluation: Model Comparison

> Note: The phrase check is an automated phrase proxy, not the two-annotator factual-support study in §9.9. Forbidden counts only phrases absent from the source note, so a correctly restated negation is not counted as an unsupported claim.

| Model | Latency p50 (s) | Latency p95 (s) | Success Rate | Required Recall | Forbidden Count | Facts Proposed | Errors (unsupported / invalid / incomplete / unavailable) |
|---|---|---|---|---|---|---|---|
| qwen3:4b | 22.3384 | 23.8163 | 100.0% | 100.0% | 0 | 26 | 0 / 0 / 0 / 0 |
| qwen3:1.7b | 11.9629 | 14.0226 | 100.0% | 100.0% | 0 | 18 | 0 / 0 / 0 / 0 |
| llama3.2:3b | 17.6778 | 25.1732 | 100.0% | 83.3% | 0 | 20 | 0 / 0 / 0 / 0 |
| gemma4:e2b | 7.1333 | 13.8488 | 100.0% | 72.2% | 0 | 19 | 0 / 0 / 0 / 0 |

## Limitations

- **Sample Size:** The evaluation is conducted on a small sample size consisting of 6 generated synthetic pages and 5 synthetic clinical cases.
- **Synthetic Pages & Handwriting (NFR-17):** The test pages are typed and synthetic, so handwriting accuracy (NFR-17) is not measured unless handwritten fixtures were supplied.
- **Proxy Targets (NFR-16):** NFR-16's 95%/85% targets are not established by this proxy. The phrase check is an automated phrase proxy, not the two-annotator factual-support study in §9.9.
- **Clinical Disclaimer:** No result produced by this evaluation harness is a claim of clinical validity or endorsement for direct patient care.
