// chart_card çizimi (Apache ECharts). Noktaları sunucu hesaplar; burada yalnızca
// çizilir: toplam, yüzde ya da sıralama istemcide türetilmez (docs/chat.md › Arayüz
// kuralları 8). Seçenekler tür başına chartOptions.ts'te kurulur; tablo, grafiğin
// erişilebilir ve denetlenebilir karşılığıdır.

import { BarChart, HeatmapChart, LineChart, PieChart } from 'echarts/charts'
import {
  GridComponent,
  LegendComponent,
  TitleComponent,
  TooltipComponent,
  VisualMapComponent,
} from 'echarts/components'
import * as echarts from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { useEffect, useRef } from 'react'
import type { ChartCard } from './chat'
import { changeLabel, chartOption, chartTitle } from './chartOptions'

echarts.use([
  BarChart,
  HeatmapChart,
  LineChart,
  PieChart,
  GridComponent,
  LegendComponent,
  TitleComponent,
  TooltipComponent,
  VisualMapComponent,
  CanvasRenderer,
])

export function Chart({ card }: { card: ChartCard }) {
  const host = useRef<HTMLDivElement>(null)
  const empty = card.items.length === 0
  const hasSeries = card.series_by !== undefined
  const hasChange = card.items.some((item) => item.change_pct !== undefined)
  const shownGroups = new Set(card.items.map((item) => item.label)).size

  useEffect(() => {
    if (host.current === null || empty) return
    const instance = echarts.init(host.current)
    instance.setOption(chartOption(card))
    const onResize = () => instance.resize()
    window.addEventListener('resize', onResize)
    return () => {
      window.removeEventListener('resize', onResize)
      instance.dispose()
    }
  }, [card, empty])

  return (
    <figure className="chart-card">
      <figcaption>{chartTitle(card)}</figcaption>
      {empty ? (
        <p className="note">Süzgeçle eşleşen uçuş yok.</p>
      ) : (
        <>
          <div ref={host} className="chart-canvas" role="img" aria-label="Grafik" />
          <table className="kpi chart-table">
            <tbody>
              {card.items.map((item) => (
                <tr key={`${item.label}|${item.series ?? ''}`}>
                  <td>{item.label}</td>
                  {hasSeries && <td>{item.series}</td>}
                  <td className="kpi-value">{item.value}</td>
                  {hasChange && <td className="kpi-value">{changeLabel(item) ?? '—'}</td>}
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
      <p className="note">
        {card.groups_total > shownGroups &&
          `${card.groups_total} gruptan ilk ${shownGroups} gösteriliyor. `}
        {(card.series_truncated ?? 0) > 0 &&
          `${card.series_truncated} seri sığmadığı için gösterilmiyor. `}
        {card.unclassified > 0 && `${card.unclassified} uçuşun bu boyutu veride yok. `}
        {card.flights} uçuş kapsamda.
      </p>
    </figure>
  )
}
