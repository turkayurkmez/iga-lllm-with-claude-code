// Tool çıktı zarfı: docs/zarf.md sözleşmesinin frontend karşılığı.
// Zarfı backend kurar; frontend yalnızca okur, alanları değiştirmez ve yeniden hesaplamaz.

// Hata kodları (docs/zarf.md › Hata kodları). erasableSyntaxOnly açık olduğu için
// TS enum yerine as const nesne ve aynı adla union tip kullanılır.
export const ErrorCode = {
  NOT_FOUND: 'NOT_FOUND',
  AMBIGUOUS_ENTITY: 'AMBIGUOUS_ENTITY',
  STALE_DATA: 'STALE_DATA',
  CAPABILITY_NOT_IN_SCOPE: 'CAPABILITY_NOT_IN_SCOPE',
  SCHEMA_VALIDATION_FAILED: 'SCHEMA_VALIDATION_FAILED',
} as const

export type ErrorCode = (typeof ErrorCode)[keyof typeof ErrorCode]

// Zarfın sekiz alanı; hepsi her yanıtta bulunur, anlamı olmayan alan null'dır.
export interface Envelope<V = unknown> {
  // Tool'un döndürdüğü veri: nesne, dizi ya da null. Hesap serviste yapılmıştır.
  value: V | null
  // Verinin kaynağı; katman hatasında null.
  source: string | null
  // Verinin ait olduğu an, +03:00 saat dilimli ISO 8601; katman hatasında null.
  as_of: string | null
  // Doğrulanmış tool argümanları; argüman doğrulanamadıysa {}.
  filters: Record<string, unknown>
  // true ise error.code STALE_DATA'dır, STALE_DATA ise stale true'dur.
  stale: boolean
  // MAJOR.MINOR.PATCH; kayıtlı olmayan tool istendiyse null.
  tool_version: string | null
  // Başarıda null.
  error: Envelope.Error | null
  // Zarfı kimin yazdığı.
  author: 'tool' | 'layer'
}

export namespace Envelope {
  // message kısa, genel bir Türkçe açıklamadır; olduğu gibi gösterilir.
  export interface Error {
    code: ErrorCode
    message: string
  }
}

const FIELDS = [
  'value',
  'source',
  'as_of',
  'filters',
  'stale',
  'tool_version',
  'error',
  'author',
] as const

// Saniye kesri isteğe bağlı: COPILOT_NOW boşken sistem saati mikrosaniyeli gelir.
const AS_OF = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?\+03:00$/
const VERSION = /^\d+\.\d+\.\d+$/
const ERROR_CODES: readonly string[] = Object.values(ErrorCode)

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function hasExactKeys(value: Record<string, unknown>, keys: readonly string[]): boolean {
  const actual = Object.keys(value)
  return actual.length === keys.length && keys.every((key) => Object.hasOwn(value, key))
}

function isNullableString(value: unknown, pattern?: RegExp): boolean {
  if (value === null) return true
  return typeof value === 'string' && (pattern === undefined || pattern.test(value))
}

function isError(value: unknown): value is Envelope.Error {
  return (
    isPlainObject(value) &&
    hasExactKeys(value, ['code', 'message']) &&
    typeof value.code === 'string' &&
    ERROR_CODES.includes(value.code) &&
    typeof value.message === 'string'
  )
}

// Gövdenin docs/zarf.md'deki zarf olup olmadığını denetler: tam sekiz alan, alan
// tipleri, hata kodu listesi ve stale ↔ STALE_DATA kuralı. Taşıma hatası gövdesi
// ({"detail": ...}) zarf değildir.
export function isEnvelope(body: unknown): body is Envelope {
  if (!isPlainObject(body) || !hasExactKeys(body, FIELDS)) return false

  const { value, source, as_of, filters, stale, tool_version, error, author } = body
  if (value !== null && typeof value !== 'object') return false
  if (!isNullableString(source)) return false
  if (!isNullableString(as_of, AS_OF)) return false
  if (!isPlainObject(filters)) return false
  if (typeof stale !== 'boolean') return false
  if (!isNullableString(tool_version, VERSION)) return false
  if (error !== null && !isError(error)) return false
  if (author !== 'tool' && author !== 'layer') return false

  const staleCode = error !== null && error.code === ErrorCode.STALE_DATA
  return stale === staleCode
}
