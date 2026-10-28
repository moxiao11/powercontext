export const MODEL = {
  id: 'Xenova/bge-small-zh-v1.5',
  revision: '75c43b069aac4d136ba6bc1122f995fedcfd2781',
  dimension: 512,
  queryPrefix: '为这个句子生成表示以用于检索相关文章：',
  maxTokens: 256,
  files: {
    fp32: { name: 'model.onnx', bytes: 94851877, sha256: '69a0b846f4f116b5e6aabf9546ea6754d02264f3211a13a1bd69b31b8040749a' },
    fp16: { name: 'model_fp16.onnx', bytes: 47497427, sha256: '60d0fe5eb8d4e251d4b24dff010a2625c10a013503f0d09f625e8a9b0311315f' },
    q8: { name: 'model_quantized.onnx', bytes: 24010842, sha256: '15b717c382bcb518ba457b93ea6850ede7f4f1cd8937454aa06972366cd19bcc' }
  }
} as const;
export type Precision = keyof typeof MODEL.files;
export type Device = 'auto' | 'webgpu' | 'wasm';
export type ModelConfig = { device: Device; precision: Precision | 'auto' };
export type EngineInfo = { backend: 'webgpu' | 'wasm'; precision: Precision; reason: string; loadMs: number; warmupMs: number; threads: number; webgpuAvailable: boolean; shaderF16: boolean; cached: boolean };
export const SPACE = `${MODEL.id}@${MODEL.revision}:cls:l2:tokens${MODEL.maxTokens}:query-prefix-v1`;
