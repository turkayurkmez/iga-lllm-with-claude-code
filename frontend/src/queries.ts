// Doğrulama sayfasının sabit sorgu listesi.
// docs/http.md › Arayüz kuralları tool adlarının ve argümanların koda gömülmesini yasaklar;
// bu liste bilinçli bir istisnadır: amaç, sözleşmeyi bilinen girdilerle sınamaktır.
// Beklenen sonuçlar data/referans/seed42-2026-10-20.json ve
// COPILOT_NOW=2026-10-20T16:22:00+03:00 içindir (docs/http.md › Örnekler).

import { ErrorCode } from './envelope'

export interface Expected {
  status: number
  // Zarf beklenmiyorsa (taşıma hatası) false.
  envelope: boolean
  code: ErrorCode | null
}

export interface Query {
  id: string
  tool: string
  // Gövde ham metin olarak gönderilir; geçersiz JSON örneği de böylece yazılabilir.
  body: string
  note: string
  expected: Expected
}

const ok: Expected = { status: 200, envelope: true, code: null }
const notFound: Expected = { status: 404, envelope: true, code: ErrorCode.NOT_FOUND }
const invalid: Expected = {
  status: 422,
  envelope: true,
  code: ErrorCode.SCHEMA_VALIDATION_FAILED,
}

export const QUERIES: Query[] = [
  {
    id: 'summary-all',
    tool: 'get_flight_summary',
    body: '{"direction": "all"}',
    note: 'Tüm uçuşlar',
    expected: ok,
  },
  {
    id: 'summary-arrival',
    tool: 'get_flight_summary',
    body: '{"direction": "arrival"}',
    note: 'Yalnızca gelen uçuşlar',
    expected: ok,
  },
  {
    id: 'summary-upper',
    tool: 'get_flight_summary',
    body: '{"direction": "ALL"}',
    note: 'Enum dışı değer (büyük harf)',
    expected: invalid,
  },
  {
    id: 'summary-extra',
    tool: 'get_flight_summary',
    body: '{"direction": "all", "airline": "TK"}',
    note: 'Ek argüman',
    expected: invalid,
  },
  {
    id: 'resolve-callsign',
    tool: 'resolve_flight_identity',
    body: '{"query": "THY2345"}',
    note: 'Callsign ile tek eşleşme',
    expected: ok,
  },
  {
    id: 'resolve-normalized',
    tool: 'resolve_flight_identity',
    body: '{"query": "thy02345"}',
    note: 'Küçük harf ve baştaki sıfır aynı kaydı bulur',
    expected: ok,
  },
  {
    id: 'resolve-ambiguous',
    tool: 'resolve_flight_identity',
    body: '{"query": "TC-LSD"}',
    note: 'Tescil iki uçuşla eşleşir (belirsizlik)',
    expected: { status: 409, envelope: true, code: ErrorCode.AMBIGUOUS_ENTITY },
  },
  {
    id: 'resolve-missing',
    tool: 'resolve_flight_identity',
    body: '{"query": "ZZ9999"}',
    note: 'Hiçbir kayıtta olmayan sefer',
    expected: notFound,
  },
  {
    id: 'details-ok',
    tool: 'get_flight_details',
    body: '{"flight_id": "FL-20261020-0270"}',
    note: 'Uçuş ayrıntısı ve son konum',
    expected: ok,
  },
  {
    id: 'details-cancelled',
    tool: 'get_flight_details',
    body: '{"flight_id": "FL-20261020-0143"}',
    note: 'İptal edilen uçuş (stand ve gate yok)',
    expected: ok,
  },
  {
    id: 'details-missing',
    tool: 'get_flight_details',
    body: '{"flight_id": "FL-20261020-9999"}',
    note: 'Biçime uyan ama olmayan flight_id',
    expected: notFound,
  },
  {
    id: 'details-format',
    tool: 'get_flight_details',
    body: '{"flight_id": "TK2345"}',
    note: 'flight_id yerine sefer no',
    expected: invalid,
  },
  {
    id: 'unknown-tool',
    tool: 'get_weather',
    body: '{}',
    note: 'Kayıtlı olmayan tool (kapsam dışı)',
    expected: { status: 404, envelope: true, code: ErrorCode.CAPABILITY_NOT_IN_SCOPE },
  },
  {
    id: 'transport-json',
    tool: 'get_flight_summary',
    body: '{direction: all}',
    note: 'Geçersiz JSON: taşıma hatası, zarf yok',
    expected: { status: 400, envelope: false, code: null },
  },
  {
    id: 'transport-array',
    tool: 'get_flight_summary',
    body: '[1]',
    note: 'Nesne olmayan JSON: zarf döner',
    expected: invalid,
  },
]
