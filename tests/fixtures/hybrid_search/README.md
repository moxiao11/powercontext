# Native hybrid search measurement

This is an independent public-development experiment, not the organizer's private quality sequence. It uses 173 original SciFact documents, 20 original development claims and three isolated scopes. It retains public relevance labels in `qrels.json` for a separate scorer. Product code and the native measurement worker do not read those labels.

Source: [SciFact](https://github.com/allenai/scifact/tree/68b98a56d93e0f9da0d2aab4e6c3294699a0f72e), by David Wadden, Shanchuan Lin, Kyle Lo, Lucy Lu Wang, Madeleine van Zuylen, Arman Cohan, and Hannaneh Hajishirzi, *Fact or Fiction: Verifying Scientific Claims* (2020). The pinned repository's script points to a mutable `latest` data archive. The actual archive SHA-256 is `11c621288d41ac144d29b13b0f8503b3820b7d6e8b1f6ff24dff335c196d76be` (3,115,079 bytes); this hash identifies the data used here.

The first 20 development claims with nonempty annotated evidence are taken in original numeric claim-ID order, without filtering by product results. All of their relevant documents are included. For each claim, the top five BM25 documents from the complete 5,183-document corpus are added, using lowercase `[a-z]+|\d+` terms, k1=1.2 and b=0.75. Remaining documents are filled in ascending SHA-256 of document ID order until there are 173 distinct documents; document order also follows that hash. Text is the original title followed by the original abstract sentences joined with spaces. No claim is rewritten.

Vectors are fixed 384-dimensional, unit-normalized float vectors computed with the [all-MiniLM-L6-v2 model](https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2) at revision `1110a243fdf4706b3f48f1d95db1a4f5529b4d41`. The upstream `onnx/model_quint8_avx2.onnx` export is run with ONNX Runtime 1.31.1, a 256-token truncation limit, attention-masked mean pooling and L2 normalization. Values are stored to eight decimal places. Model and tokenizer file hashes are included in `inputs.json`. These precomputed vectors make native comparisons offline; the model runtime is not a product or self-test dependency.

`frozen_memory_index.py` is the unchanged OceanBase Memory index source from PowerContext commit `9db1753434162c0aa7c9f1189a1722e617880a52`, SHA-256 `9ea1af189bb9a1dfaed52658febb9ccc7577931f2b0a9d107938f2901ed0fc37`. It is used only to run the frozen dual-query control against the same database and persisted identities. No grader files are replaced.

`measure.py` runs with real `pylibseekdb==1.3.0.post4` and the product's SQLAlchemy connection. In each scope, the product writes all documents with the fixed embedding model. Candidate and control use the same head, query and query vector through complete `Memory.search` calls, at limit=10. Each path is warmed once per scope, and the first path alternates by query. Statement listeners verify one native candidate statement for the new path and two for the frozen path; head validation and exact entry reads are outside that count but inside search latency. Every hit is checked against the persisted entry version, exact text and current head. Additional repeated queries check stable identities and order outside the timing sample. An actual EXPLAIN verifies both native index operators. The worker reads only `inputs.json` and emits observations.

`score.py` is a separate standard-library-only process. It reads the public qrels and observations, computes Recall@10 and MRR@10 per query, checks nondegradation, and reports full-ranking agreement and median complete-search latency. These observations do not certify the private sequence or prove a general end-to-end speedup.

Run with the fixed Python 3.12 self-test environment and product source on PYTHONPATH:

```sh
python tests/fixtures/hybrid_search/measure.py tests/fixtures/hybrid_search/inputs.json > observations.json
python tests/fixtures/hybrid_search/score.py observations.json measurement.json
```

The embedded engine requires its normal supported Linux environment and a non-loopback address. The competition Docker entrypoint supplies that address even with networking disabled. Inputs, vectors and dependencies are sufficient for offline measurement after setup.

Claims and evidence annotations are [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). Abstracts are from Semantic Scholar S2ORC under [ODC-By 1.0](https://opendatacommons.org/licenses/by/1-0/). The copied upstream [LICENSE.md](LICENSE.md) retains the source terms. The model is Apache 2.0; this fixture stores its output vectors and provenance, not its weights. The scripts and frozen reference source retain the product's Apache 2.0 license.
