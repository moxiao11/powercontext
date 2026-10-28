import type { EngineInfo } from './model';
export type Chunk = { id: string; text: string; metadata: { documentId: string; title: string; source: string; chunk: number; chunks: number; importedAt: string } };
export type KnowledgeBase = { id: string; name: string; count: number; documents: number; generation: number; refreshedGeneration: number; createdAt: string; status: string };
export type SearchHit = { id: string; text: string; metadata: Chunk['metadata']; rank: number; distance: number | null };
export type Timing = { embeddingMs: number; requestMs: number; searchMs: number; endToEndMs: number };
export type SearchResponse = { hits: SearchHit[]; searchMs: number; generation: number; engine: string };
export type BenchRow = { profile: string; repeat: number; engine: EngineInfo; batchSize: number; writeBatch: number; refreshStrategy: string; chunkCount: number; queryCount: number; embeddingMs: number; throughput: number; writeMs: number; refreshMs: number; firstQuery: Timing; queries: Array<Timing & { id: string; recall: number; ndcg: number; hits: string[] }>; recall: number; ndcg: number; modelBytes: number; totalMs: number };
