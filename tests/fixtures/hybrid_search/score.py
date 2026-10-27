# Copyright (c) 2026 OceanBase.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Independent standard-library scorer for the public-development experiment."""

from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path


def quality(hits, relevant):
    documents = [hit["document_id"] for hit in hits[:10]]
    recall = len(set(documents) & set(relevant)) / len(relevant)
    reciprocal = next((1 / position for position, doc in enumerate(documents, 1) if doc in relevant), 0)
    return recall, reciprocal


def score(observations, qrels):
    rows = []
    for row in observations["rows"]:
        candidate = row["candidate"]
        frozen = row["frozen"]
        cr, cm = quality(candidate["hits"], qrels[row["query_id"]])
        fr, fm = quality(frozen["hits"], qrels[row["query_id"]])
        rows.append({
            "scope": row["scope"],
            "query_id": row["query_id"],
            "candidate_recall_at_10": cr,
            "candidate_mrr_at_10": cm,
            "frozen_recall_at_10": fr,
            "frozen_mrr_at_10": fm,
            "candidate_latency_ms": candidate["latency_ms"],
            "frozen_latency_ms": frozen["latency_ms"],
            "candidate_statements": candidate["candidate_statements"],
            "nondecreasing": cr >= fr and cm >= fm,
            "identical_ranking": candidate["hits"] == frozen["hits"],
        })
    assert len(rows) == 60 and len({row["query_id"] for row in rows}) == 20
    median = statistics.median(row["candidate_latency_ms"] for row in rows)
    frozen_median = statistics.median(row["frozen_latency_ms"] for row in rows)
    summary = {
        "requests": len(rows),
        "scopes": 3,
        "documents_per_scope": 173,
        "evidence_recall_at_10": statistics.mean(row["candidate_recall_at_10"] for row in rows),
        "mean_mrr_at_10": statistics.mean(row["candidate_mrr_at_10"] for row in rows),
        "frozen_recall_at_10": statistics.mean(row["frozen_recall_at_10"] for row in rows),
        "frozen_mean_mrr_at_10": statistics.mean(row["frozen_mrr_at_10"] for row in rows),
        "nondecreasing_queries": sum(row["nondecreasing"] for row in rows),
        "identical_ranking_fraction": sum(row["identical_ranking"] for row in rows) / len(rows),
        "p50_latency_ms": median,
        "frozen_p50_latency_ms": frozen_median,
        "p50_latency_ratio": median / frozen_median,
        "one_candidate_statement_each": all(row["candidate_statements"] == 1 for row in rows),
    }
    return {
        "source": observations["source"],
        "embedding": observations["embedding"],
        "profile": observations["profile"],
        "frozen_index_sha256": observations["frozen_index_sha256"],
        "explain": observations["explain"],
        "summary": summary,
        "rows": rows,
    }


if __name__ == "__main__":
    report = score(
        json.loads(Path(sys.argv[1]).read_text(encoding="utf-8")),
        json.loads(Path(__file__).with_name("qrels.json").read_text(encoding="utf-8")),
    )
    Path(sys.argv[2]).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report["summary"], indent=2))
