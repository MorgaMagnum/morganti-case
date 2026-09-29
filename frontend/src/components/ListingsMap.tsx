/// <reference types="leaflet.markercluster" />
import { useQuery } from '@tanstack/react-query'
import L from 'leaflet'
import { useEffect, useMemo, useRef, useState } from 'react'
import { GeoJSON, MapContainer, Marker, Popup, TileLayer, useMap, useMapEvents } from 'react-leaflet'
import MarkerClusterGroup from 'react-leaflet-cluster'
import { Link } from 'react-router-dom'
import type { Contract, MapMarker, PositionCertainty } from '../api/types'
import { capitalize, formatPrice, PRECISION_LABEL } from '../lib/format'
import Legend from './Legend'

export const CASCINA_CENTER: [number, number] = [43.675, 10.5]
const TILE_URL = 'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png'
const TILE_ATTRIBUTION = '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'

const iconCache = new Map<string, L.DivIcon>()
function markerIcon(contract: Contract, certain: boolean, highlighted = false): L.DivIcon {
  const key = `${contract}-${certain}-${highlighted}`
  let icon = iconCache.get(key)
  if (!icon) {
    const size = highlighted ? 28 : certain ? 16 : 18
    icon = L.divIcon({
      className: `mk mk-${contract}${certain ? '' : ' mk-uncertain'}${highlighted ? ' mk-hl' : ''}`,
      // Uncertain pins are hollow with a "?" so they never read as a real address.
      html: certain ? '<span></span>' : '<span>?</span>',
      iconSize: [size, size],
      iconAnchor: [size / 2, size / 2],
    })
    iconCache.set(key, icon)
  }
  return icon
}

function makeClusterIcon(certain: boolean) {
  return (cluster: L.MarkerCluster): L.DivIcon => {
    const children = cluster.getAllChildMarkers()
    const rent = children.filter((m) => (m.options.icon?.options.className ?? '').includes('mk-affitto')).length
    const share = Math.round((rent / children.length) * 360)
    const n = children.length
    const size = n < 10 ? 34 : n < 50 ? 40 : n < 200 ? 48 : 56
    return L.divIcon({
      className: `cluster${certain ? '' : ' cluster-uncertain'}`,
      html: `<div style="--rent-share:${share}deg"><span>${certain ? n : `${n}?`}</span></div>`,
      iconSize: [size, size],
    })
  }
}
const certainClusterIcon = makeClusterIcon(true)
const uncertainClusterIcon = makeClusterIcon(false)

function BoundsWatcher({ onChange }: { onChange: (bbox: string) => void }) {
  const map = useMapEvents({
    moveend: () => report(),
  })
  const report = () => {
    const b = map.getBounds()
    onChange([b.getWest(), b.getSouth(), b.getEast(), b.getNorth()].map((v) => v.toFixed(5)).join(','))
  }
  useEffect(report, []) // eslint-disable-line react-hooks/exhaustive-deps
  return null
}

function FitToBoundary({ data }: { data: GeoJSON.GeoJsonObject | undefined }) {
  const map = useMap()
  const done = useRef(false)
  useEffect(() => {
    if (!data || done.current) return
    done.current = true
    map.fitBounds(L.geoJSON(data).getBounds(), { padding: [12, 12] })
  }, [data, map])
  return null
}

interface Props {
  markers: MapMarker[]
  highlightedId: number | null
  contract: Contract | null
  position: PositionCertainty | null
  counts: Record<Contract, number>
  positionCounts: Record<PositionCertainty, number>
  loading: boolean
  onContractToggle: (c: Contract) => void
  onPositionToggle: (p: PositionCertainty) => void
  onBoundsChange: (bbox: string) => void
}

export default function ListingsMap({
  markers,
  highlightedId,
  contract,
  position,
  counts,
  positionCounts,
  loading,
  onContractToggle,
  onPositionToggle,
  onBoundsChange,
}: Props) {
  const boundary = useQuery({
    queryKey: ['boundary'],
    queryFn: async () => {
      const res = await fetch('/api/boundary')
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      return (await res.json()) as GeoJSON.GeoJsonObject
    },
    staleTime: Infinity,
  })
  const [selected, setSelected] = useState<MapMarker | null>(null)

  const highlighted = useMemo(() => markers.find((m) => m.id === highlightedId) ?? null, [markers, highlightedId])

  // Listings with no location info at all would only pile up on a fake point in the
  // town centre: they are listed below the map but not drawn.
  const unplaced = useMemo(() => markers.filter((m) => m.geo_precision === 'comune').length, [markers])

  // Two cluster groups so a "certain" cluster never swallows made-up positions.
  // One shared popup instead of one (portal-rendered) popup per marker.
  const [certainEls, uncertainEls] = useMemo(() => {
    const toMarker = (m: MapMarker) => (
      <Marker
        key={m.id}
        position={[m.lat, m.lng]}
        icon={markerIcon(m.contract, m.position_certain)}
        eventHandlers={{ click: () => setSelected(m) }}
      />
    )
    return [
      markers.filter((m) => m.position_certain).map(toMarker),
      markers.filter((m) => !m.position_certain && m.geo_precision !== 'comune').map(toMarker),
    ]
  }, [markers])

  return (
    <div className="map-wrap">
      <MapContainer center={CASCINA_CENTER} zoom={13} zoomSnap={0.25} scrollWheelZoom className="map">
        <TileLayer url={TILE_URL} attribution={TILE_ATTRIBUTION} />
        {boundary.data && (
          <GeoJSON data={boundary.data} style={{ color: '#1f3a2e', weight: 2, dashArray: '6 6', fillOpacity: 0.03 }} interactive={false} />
        )}
        <FitToBoundary data={boundary.data} />
        <BoundsWatcher onChange={onBoundsChange} />
        <MarkerClusterGroup chunkedLoading maxClusterRadius={45} showCoverageOnHover={false} spiderfyOnMaxZoom iconCreateFunction={certainClusterIcon}>
          {certainEls}
        </MarkerClusterGroup>
        <MarkerClusterGroup chunkedLoading maxClusterRadius={45} showCoverageOnHover={false} spiderfyOnMaxZoom iconCreateFunction={uncertainClusterIcon}>
          {uncertainEls}
        </MarkerClusterGroup>
        {selected && (
          <Popup key={selected.id} position={[selected.lat, selected.lng]} eventHandlers={{ remove: () => setSelected(null) }}>
            <div className="map-popup">
              <strong>{formatPrice(selected.price, selected.contract)}</strong>
              <span>
                {capitalize(selected.property_type)} · {selected.contract}
              </span>
              <em className={selected.position_certain ? '' : 'uncertain-note'}>
                {selected.position_certain ? 'Posizione certa' : 'Posizione incerta'} ({PRECISION_LABEL[selected.geo_precision].toLowerCase()})
              </em>
              <Link to={`/immobile/${selected.id}`}>Apri scheda →</Link>
            </div>
          </Popup>
        )}
        {highlighted && (
          <Marker
            position={[highlighted.lat, highlighted.lng]}
            icon={markerIcon(highlighted.contract, highlighted.position_certain, true)}
            zIndexOffset={1000}
            interactive={false}
          />
        )}
      </MapContainer>
      <Legend
        contract={contract}
        position={position}
        counts={counts}
        positionCounts={positionCounts}
        unplaced={unplaced}
        onToggle={onContractToggle}
        onPositionToggle={onPositionToggle}
      />
      {loading && <div className="map-loading">Carico gli immobili…</div>}
    </div>
  )
}
