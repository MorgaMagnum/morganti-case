import { useRef, useState } from 'react'
import type { DragEvent, ReactNode } from 'react'
import { api } from '../api/client'
import { importMessage, useCsvImport } from '../hooks/useCsvImport'

/** Picks a .csv file (button or drag & drop), uploads it and reports the outcome. */
export function ImportCsv(props: { label?: string; className?: string; dropZone?: boolean; children?: ReactNode }) {
  const input = useRef<HTMLInputElement>(null)
  const [dragging, setDragging] = useState(false)
  const importer = useCsvImport()

  const send = (file: File | undefined) => {
    if (file) importer.mutate(file)
    if (input.current) input.current.value = '' // allow picking the same file again
  }
  const dropHandlers = props.dropZone
    ? {
        onDragOver: (e: DragEvent) => {
          e.preventDefault()
          setDragging(true)
        },
        onDragLeave: () => setDragging(false),
        onDrop: (e: DragEvent) => {
          e.preventDefault()
          setDragging(false)
          send(e.dataTransfer.files[0])
        },
      }
    : {}

  return (
    <div className={`import-csv ${props.dropZone ? 'drop-zone' : ''} ${dragging ? 'is-dragging' : ''}`} {...dropHandlers}>
      <input ref={input} type="file" accept=".csv,text/csv" hidden onChange={(e) => send(e.target.files?.[0])} />
      {props.children}
      <button
        type="button"
        className={props.className ?? 'btn'}
        disabled={importer.isPending}
        onClick={() => input.current?.click()}
        title="Carica un file esportato da Cerca Case: aggiunge e aggiorna gli immobili, non cancella nulla"
      >
        {importer.isPending ? 'Importo…' : (props.label ?? 'Importa CSV')}
      </button>
      {importer.isSuccess && (
        <p className="import-result" role="status">
          {importMessage(importer.data)}
        </p>
      )}
      {importer.isError && (
        <p className="import-result error-text" role="alert">
          {(importer.error as Error).message}
        </p>
      )}
    </div>
  )
}

export function ExportCsv() {
  return (
    <a
      className="btn"
      href={api.exportUrl}
      download
      title="Scarica tutti gli immobili in un file, da importare nella versione consultazione"
    >
      Esporta CSV
    </a>
  )
}
