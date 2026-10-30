// chart_card için ECharts seçenekleri: tür başına bir üretici. Saf fonksiyonlardır
// (React ve ECharts import'u yok), bu yüzden node ile sınanabilir. Sayılar sunucudan
// olduğu gibi çizilir; toplam, yüzde ya da sıralama türetilmez, pasta yüzdesi yoktur
// (docs/chat.md › Arayüz kuralları 8). Yalnızca yerleştirme ve görünüm kurulur.

import type { ChartCard, ChartDimension, ChartItem, ChartType, Trend } from './chat'

export type EChartsOption = Record<string, unknown>

const ARROWS: Record<Trend, string> = { up: '▲', down: '▼', flat: '▬' }
const COLORS: Record<Trend, string> = { up: '#2e7d32', down: '#c62828', flat: '#757575' }
const STACK = 'toplam'

// Alan, ölçü ve işleç adlarının ekran karşılıkları yalnızca görünümdür; bilinmeyen
// kod olduğu gibi gösterilir.
const FIELD_LABELS: Record<string, string> = {
  airline: 'Havayolu',
  flight_no: 'Sefer no',
  callsign: 'Callsign',
  registration: 'Tescil',
  aircraft_type: 'Uçak tipi',
  origin: 'Kalkış',
  destination: 'Varış',
  code_letter: 'Kod harfi',
  operator_iata: 'İşletmeci',
  movement_type: 'Yön',
  stand_code: 'Stand',
  gate_code: 'Gate',
  stand_type: 'Stand türü',
  max_code_letter: 'Stand kod harfi',
  delay_code: 'Gecikme kodu',
  delay_category: 'Gecikme nedeni',
  cancelled: 'İptal',
  status: 'Durum',
  scheduled_time: 'Planlanan saat',
  estimated_time: 'Tahmini saat',
  actual_runway_time: 'Pist saati',
  actual_block_time: 'Blok saati',
  delay_minutes: 'Gecikme (dk)',
}
const AGG_LABELS: Record<string, string> = {
  count: 'Uçuş sayısı',
  sum: 'Toplam',
  avg: 'Ortalama',
  min: 'En küçük',
  max: 'En büyük',
}
const OP_LABELS: Record<string, string> = {
  eq: '=',
  ne: '≠',
  in: 'içinde',
  gt: '>',
  ge: '≥',
  lt: '<',
  le: '≤',
}
const BUCKET_LABELS: Record<string, string> = { hour: 'saat', half_hour: 'yarım saat' }

function fieldLabel(field: string): string {
  return FIELD_LABELS[field] ?? field
}

function dimensionLabel(dimension: ChartDimension): string {
  const bucket = dimension.bucket === undefined ? '' : ` (${BUCKET_LABELS[dimension.bucket] ?? dimension.bucket})`
  return `${fieldLabel(dimension.field)}${bucket}`
}

function measureLabel(card: ChartCard): string {
  if (card.plot === 'change_pct') return 'Önceki kovaya göre değişim (%)'
  const { agg, field } = card.measure
  const name = AGG_LABELS[agg] ?? agg
  return field === undefined ? name : `${name} ${fieldLabel(field)}`
}

function filterTexts(card: ChartCard): string[] {
  const filters = card.filters.filters
  if (!Array.isArray(filters)) return []
  return filters.map((item: unknown) => {
    const { field, op, value } = item as Record<string, unknown>
    const shown = Array.isArray(value) ? value.join(', ') : String(value)
    return `${fieldLabel(String(field))} ${OP_LABELS[String(op)] ?? String(op)} ${shown}`
  })
}

// "ölçü · grup[ × seri] · süzgeçler · tarih" görünüm metni.
export function chartTitle(card: ChartCard): string {
  const group = dimensionLabel(card.group_by)
  const grouping = card.series_by === undefined ? group : `${group} × ${dimensionLabel(card.series_by)}`
  return [measureLabel(card), grouping, ...filterTexts(card), card.date].join(' · ')
}

// "▲ 12,5%" / "▼ 3,0%" / "▬ 0,0%": sunucunun trend ve change_pct alanlarından; ondalık
// ayracı yalnızca görünümdür, değer yeniden hesaplanmaz.
export function changeLabel(item: ChartItem): string | null {
  if (item.change_pct === undefined || item.trend === undefined) return null
  const number = Math.abs(item.change_pct).toFixed(1).replace('.', ',')
  return `${ARROWS[item.trend]} ${number}%`
}

function distinct(values: string[]): string[] {
  return [...new Set(values)]
}

function seriesNames(card: ChartCard): string[] {
  return card.series_by === undefined ? [measureLabel(card)] : distinct(card.items.map((i) => i.series ?? ''))
}

function cellItem(card: ChartCard, label: string, series: string | undefined): ChartItem | undefined {
  return card.items.find((item) => item.label === label && item.series === series)
}

// Kategori (grup) etiketleri; değişim çiziliyorsa değişimi olmayan kova çizilmez.
function categories(card: ChartCard): string[] {
  const plotted = card.plot === 'change_pct' ? card.items.filter((i) => i.change_pct !== undefined) : card.items
  return distinct(plotted.map((item) => item.label))
}

function point(card: ChartCard, item: ChartItem | undefined): unknown {
  if (item === undefined) return null
  if (card.plot !== 'change_pct') return item.value
  if (item.change_pct === undefined || item.trend === undefined) return null
  return {
    value: item.change_pct,
    label: { show: true, formatter: changeLabel(item) },
    itemStyle: { color: COLORS[item.trend] },
  }
}

function cartesianSeries(card: ChartCard, kind: 'bar' | 'line', stacked: boolean, area: boolean): EChartsOption[] {
  const labels = categories(card)
  return seriesNames(card).map((name) => ({
    type: kind,
    name,
    ...(stacked ? { stack: STACK } : {}),
    ...(area ? { areaStyle: {} } : {}),
    data: labels.map((label) =>
      point(card, cellItem(card, label, card.series_by === undefined ? undefined : name)),
    ),
  }))
}

function cartesian(card: ChartCard, kind: 'bar' | 'line', options: { horizontal?: boolean; stacked?: boolean; area?: boolean }): EChartsOption {
  const category = { type: 'category', data: categories(card) }
  const value = { type: 'value' }
  return {
    tooltip: { trigger: 'axis' },
    grid: { containLabel: true, left: 8, right: 24, top: 32, bottom: card.series_by === undefined ? 8 : 40 },
    ...(card.series_by === undefined ? {} : { legend: { type: 'scroll', bottom: 0 } }),
    // Yatay çubukta ilk kategori üstte durur (kategori ekseni tersten çizilir).
    xAxis: options.horizontal ? value : category,
    yAxis: options.horizontal ? { ...category, inverse: true } : value,
    series: cartesianSeries(card, kind, options.stacked === true, options.area === true),
  }
}

function pie(card: ChartCard, radius: string | string[]): EChartsOption {
  return {
    tooltip: { trigger: 'item', formatter: '{b}: {c}' },
    legend: { type: 'scroll', bottom: 0 },
    series: [
      {
        type: 'pie',
        name: measureLabel(card),
        radius,
        label: { formatter: '{b}' },
        data: card.items.map((item) => ({ name: item.label, value: item.value })),
      },
    ],
  }
}

function heatmap(card: ChartCard): EChartsOption {
  const x = distinct(card.items.map((item) => item.label))
  const y = distinct(card.items.map((item) => item.series ?? ''))
  const values = card.items.map((item) => item.value)
  return {
    tooltip: { position: 'top' },
    grid: { containLabel: true, left: 8, right: 24, top: 8, bottom: 56 },
    xAxis: { type: 'category', data: x, splitArea: { show: true } },
    yAxis: { type: 'category', data: y, splitArea: { show: true } },
    // Renk ölçeği ECharts'a verilir; ek bir sayı olarak gösterilmez.
    visualMap: {
      min: values.length === 0 ? 0 : Math.min(...values),
      max: values.length === 0 ? 0 : Math.max(...values),
      calculable: true,
      orient: 'horizontal',
      left: 'center',
      bottom: 0,
    },
    series: [
      {
        type: 'heatmap',
        name: measureLabel(card),
        label: { show: true },
        data: card.items.map((item) => [x.indexOf(item.label), y.indexOf(item.series ?? ''), item.value]),
      },
    ],
  }
}

export const CHART_RENDERERS: Record<ChartType, (card: ChartCard) => EChartsOption> = {
  bar_horizontal: (card) => cartesian(card, 'bar', { horizontal: true }),
  bar_vertical: (card) => cartesian(card, 'bar', {}),
  stacked_bar: (card) => cartesian(card, 'bar', { stacked: true }),
  grouped_bar: (card) => cartesian(card, 'bar', {}),
  pie: (card) => pie(card, '60%'),
  doughnut: (card) => pie(card, ['40%', '65%']),
  line: (card) => cartesian(card, 'line', {}),
  area: (card) => cartesian(card, 'line', { area: true }),
  heatmap,
}

export function chartOption(card: ChartCard): EChartsOption {
  return CHART_RENDERERS[card.chart_type](card)
}
