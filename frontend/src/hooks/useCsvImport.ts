import { useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '../api/client'

/** Upload an exported CSV; on success every view is refreshed with the new data. */
export function useCsvImport() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (file: File) => (await api.importCsv(file)).data!,
    onSuccess: () => queryClient.invalidateQueries({ predicate: (q) => q.queryKey[0] !== 'info' }),
  })
}

export function importMessage(r: { new: number; updated: number; unchanged: number; error_count: number }): string {
  const parts = [
    r.new ? `${r.new} nuovi` : null,
    r.updated ? `${r.updated} aggiornati` : null,
    r.unchanged ? `${r.unchanged} già presenti` : null,
  ].filter(Boolean)
  const done = parts.length ? `Importati: ${parts.join(', ')}.` : 'Nessun immobile nel file.'
  return r.error_count ? `${done} ${r.error_count} righe scartate.` : done
}
