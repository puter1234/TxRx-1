import { create } from 'zustand'
import type { Brand, Checks, LogItem, ServerState } from './types'

export interface WizardState {
  step: 1 | 2 | 3
  brandId: string | null
  checks: Checks
  countMode: 'target' | 'continuous'
  target: number
  sku: string
  color: string
  size: string
}

const emptyChecks: Checks = { rfid: false, ocr: false, barcode_tag: false, barcode_poly: false }

const initialWizard: WizardState = {
  step: 1,
  brandId: null,
  checks: { ...emptyChecks },
  countMode: 'target',
  target: 40,
  sku: '',
  color: '',
  size: '',
}

interface AppStore {
  connected: boolean
  server: ServerState | null
  logs: LogItem[]
  brands: Brand[]
  wizard: WizardState
  setConnected: (v: boolean) => void
  setServer: (s: ServerState) => void
  pushLog: (item: LogItem) => void
  setLogs: (items: LogItem[]) => void
  setBrands: (b: Brand[]) => void
  setWizard: (p: Partial<WizardState>) => void
  resetWizard: () => void
}

export const useApp = create<AppStore>((set) => ({
  connected: false,
  server: null,
  logs: [],
  brands: [],
  wizard: { ...initialWizard, checks: { ...emptyChecks } },
  setConnected: (v) => set({ connected: v }),
  setServer: (server) => set({ server }),
  pushLog: (item) => set((s) => ({ logs: [...s.logs.slice(-199), item] })),
  setLogs: (items) => set({ logs: items }),
  setBrands: (brands) => set({ brands }),
  setWizard: (p) => set((s) => ({ wizard: { ...s.wizard, ...p } })),
  resetWizard: () => set({ wizard: { ...initialWizard, checks: { ...emptyChecks } } }),
}))
