# Literal evidence selection measurement

This fixture is a local public-development measurement, not the competition's private 48-request sequence. The candidate implementation receives only queries and three literal documents. It does not read `gold.json`, the source dataset, or document labels.

Source: [SciFact](https://github.com/allenai/scifact/tree/68b98a56d93e0f9da0d2aab4e6c3294699a0f72e), by David Wadden, Shanchuan Lin, Kyle Lo, Lucy Lu Wang, Madeleine van Zuylen, Arman Cohan, and Hannaneh Hajishirzi, *Fact or Fiction: Verifying Scientific Claims* (2020).

The repository's pinned download script points to the [public data archive](https://scifact.s3-us-west-2.amazonaws.com/release/latest/data.tar.gz). The downloaded archive's SHA-256 is `11c621288d41ac144d29b13b0f8503b3820b7d6e8b1f6ff24dff335c196d76be`; the repository commit identifies the download script, not a separately versioned data archive. `inputs.json` and `gold.json` preserve this provenance.

Claims are taken in ascending original development claim ID order. The collection contains the first 24 claims with exactly one annotated evidence document and a full-gold rendering that fits a conservative 1,360-byte feasibility check. Selection of cases does not depend on the candidate's scores. Gold sentence indices are united across that claim's annotations; character offsets refer to the title plus a space plus the original abstract sentences joined with spaces.

Each input contains the evidence document and two lexically strong distractors from the original 5,183-document corpus, excluding identical texts. Distractors use corpus document frequency, BM25 term weighting and a deterministic document-ID tie break. Input ordering uses SHA-256 of claim ID and document ID, so the evidence document has no fixed slot. There are 24 queries and two budgets, 1,400 and 1,800 bytes, giving 48 requests per mode.

`measure.py` runs both ordinary and selection modes over the same real Memory candidates. It captures all three documents as Sources, flushes a literal extraction pipeline, and reads the persisted Memory entries. It passes all three recalled candidates to the Builder without gold information. Every selected fragment is checked through a real historical Memory citation. The worker reads only `inputs.json` and emits observations, including all candidate citations.

`score.py` is an independent standard-library-only process. It merges overlapping/adjacent selected intervals in the gold document, computes lowercase `[a-z]+|\d+` token multiset recall and full interval coverage, and checks full-gold feasibility again with the actual native citations. It does not import candidate code. The quality thresholds are observational checks against this fixture; they do not certify the private sequence.

Run in the configured Python environment from the product root:

```sh
PYTHONPATH=src python tests/fixtures/evidence_selection/measure.py tests/fixtures/evidence_selection/inputs.json > observations.json
python tests/fixtures/evidence_selection/score.py observations.json measurement.json
```

Both commands are offline once dependencies and the fixture are present. Use the official Python 3.12 self-test environment for comparison with the competition configuration.

Claims and evidence annotations are licensed under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). Abstracts are from Semantic Scholar S2ORC and licensed under [ODC-By 1.0](https://opendatacommons.org/licenses/by/1-0/). See the copied upstream [LICENSE.md](LICENSE.md). The measurement scripts use the product repository's Apache 2.0 license.
