# Bluesky feed reply metadata research

## Findings
- The Bluesky post record schema includes an optional `reply` field that contains both `root` and `parent` references, so feed items can indicate when they are replies to other posts. This is represented by `ReplyRef` on the `Record` model in the `atproto` client (fields: `parent`, `root`, and `py_type`).
- Because the home timeline fetch (`get_timeline`) returns posts authored by followed accounts (including replies), self-replies by the same author can appear in the fetched posts. However, only posts present in the filtered timeline batch are available, so ancestor posts may be missing if they fall outside the fetched range.

## Updated task framing
When adding self-thread detection over the fetched posts:
- Inspect each post's `record.reply` (root/parent URIs) to build chains, and ensure every hop in a candidate chain has the same author handle/DID.
- Work only with the already-filtered posts set; if parent/root posts are absent from the fetched data, the chain should stop at the first missing link rather than reaching outside the dataset.
- Prefer chains with at least two posts to qualify as a self-thread.
