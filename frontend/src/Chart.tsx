// chart_card çizimi (Apache ECharts). Noktaları sunucu hesaplar; burada yalnızca
// çizilir: toplam, yüzde ya da sıralama istemcide türetilmez (docs/chat.md › Arayüz
// kuralları 8). Tablo, grafiğin erişilebilir ve denetlenebilir karşılığıdır.

import { BarChart, LineChart, PieChart } from 'echarts/charts'
import { GridComponent, LegendComponent, TitleComponent, TooltipComponent } from 'echarts/components'
import * as echarts from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { useEffect, useRef } from 'react'
import type { ChartCard } from './chat'

echarts.use([
  BarChart,
  LineChart,
  PieChart,
  GridComponent,
  LegendComponent,
  TitleComponent,
  TooltipComponent,
  CanvasRenderer,
])

// Olay verisindeki kodların ekran adları; bilinmeyen kod olduğu gibi gösterilir.
const GROUP_LABELS: Record<string, string> = {
  airline: 'Havayolu',
  aircraft_type: 'Uçak tipi',
  origin: 'Kalkış',
  destination: 'Varış',
  stand: 'Stand',
  gate: 'Gate',
  hour: 'Saat dilimi',
  status: 'Durum',
}
const METRIC_LABELS: Record<string, string> = {
  count: 'Uçuş sayısı',
  total_delay_minutes: 'Toplam gecikme (dk)',
  avg_delay_minutes: 'Ortalama gecikme (dk)',
}
const DIRECTION_LABELS: Record<string, string> = {
  all: 'tüm uçuşlar',
  arrival: 'gelen uçuşlar',
  departure: 'giden uçuşlar',
}

function label(map: Record<string, string>, key: string): string {
  return map[key] ?? key
}

function option(card: ChartCard): echarts.EChartsCoreOption {
  const labels = card.items.map((item) => item.label)
  const values = card.items.map((item) => item.value)
  const metric = label(METRIC_LABELS, card.metric)
  if (card.chart_type === 'pie') {
    return {
      tooltip: { trigger: 'item' },
      legend: { type: 'scroll', bottom: 0 },
      series: [
        {
          type: 'pie',
          name: metric,
          radius: '60%',
          data: card.items.map((item) => ({ name: item.label, value: item.value })),
        },
      ],
    }
  }
  const category = { type: 'category' as const, data: labels }
  const value = { type: 'value' as const, name: metric }
  const horizontal = card.chart_type === 'bar_horizontal'
  return {
    tooltip: { trigger: 'axis' },
    grid: { containLabel: true, left: 8, right: 24, top: 32, bottom: 8 },
    // Yatay çubukta en büyük değer üstte durur (kategori ekseni tersten çizilir).
    xAxis: horizontal ? value : category,
    yAxis: horizontal ? { ...category, inverse: true } : value,
    series: [
      {
        type: card.chart_type === 'line' ? 'line' : 'bar',
        name: metric,
        data: values,
      },
    ],
  }
}

export function Chart({ card }: { card: ChartCard }) {
  const host = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (host.current === null) return
    const instance = echarts.init(host.current)
    instance.setOption(option(card))
    const onResize = () => instance.resize()
    window.addEventListener('resize', onResize)
    return () => {
      window.removeEventListener('resize', onResize)
      instance.dispose()
    }
  }, [card])

  const direction = label(DIRECTION_LABELS, String(card.filters.direction ?? 'all'))
  return (
    <figure className="chart-card">
      <figcaption>
        {label(METRIC_LABELS, card.metric)} · {label(GROUP_LABELS, card.group_by)} · {direction} ·{' '}
        {card.date}
      </figcaption>
      <div ref={host} className="chart-canvas" role="img" aria-label="Grafik" />
      <table className="kpi chart-table">
        <tbody>
          {card.items.map((item) => (
            <tr key={item.label}>
              <td>{item.label}</td>
              <td className="kpi-value">{item.value}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="note">
        {card.groups_total > card.items.length &&
          `${card.groups_total} gruptan ilk ${card.items.length} gösteriliyor. `}
        {card.unclassified > 0 && `${card.unclassified} uçuşun bu boyutu veride yok. `}
        {card.flights} uçuş kapsamda.
      </p>
    </figure>
  )
}
