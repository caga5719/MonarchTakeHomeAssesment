/** Typed fetch wrappers for the FastAPI backend. */

export interface Summary {
  total_invoices: number
  total_spend: number
  total_line_items: number
  properties_count: number
  top_gl: { gl_code: number; gl_desc: string; total_spend: number } | null
  top_property: { property_code: string; total_spend: number } | null
  needs_review_count: number
}

export interface GLSpendItem {
  gl_code: number
  gl_desc: string
  total_spend: number
  item_count: number
}

export interface GLLineItemDetail {
  invoice_number: string
  property_code: string | null
  description: string
  subtotal: number | null
}

export interface ItemsPerGLEntry {
  gl_code: number
  gl_desc: string
  item_count: number
  total_spend: number
  items: GLLineItemDetail[]
}

export interface ItemsPerPropertyEntry {
  property_code: string
  item_count: number
  total_spend: number
  invoice_count: number
}

export interface InvoiceListItem {
  id: number
  invoice_number: string
  property_code: string | null
  invoice_gl_code: number | null
  invoice_gl_desc: string | null
  invoice_date: string | null
  purchaser: string | null
  total_amount: number | null
  needs_review: boolean
}

export interface PaginatedInvoices {
  items: InvoiceListItem[]
  total: number
  page: number
  page_size: number
}

export interface LineItemDetail {
  id: number
  line_number: number | null
  description: string
  asin: string | null
  quantity: number | null
  unit_price: number | null
  subtotal: number | null
  tax_rate: number | null
  assigned_gl_code: number | null
  assigned_gl_desc: string | null
  classification_note: string | null
  needs_review: boolean
}

export interface InvoiceDetail extends Omit<InvoiceListItem, 'total_amount'> {
  due_date: string | null
  po_number: string | null
  subtotal: number | null
  tax: number | null
  total_amount: number | null
  filename: string
  line_items: LineItemDetail[]
}

export interface MismatchItem {
  invoice_number: string
  property_code: string | null
  invoice_gl_code: number | null
  invoice_gl_desc: string | null
  line_item_desc: string
  assigned_gl_code: number
  assigned_gl_desc: string | null
  subtotal: number | null
}

export interface NeedsReviewItem {
  id: number
  invoice_number: string
  property_code: string | null
  description: string
  classification_note: string | null
  invoice_gl_code: number | null
  invoice_gl_desc: string | null
}

async function get<T>(path: string): Promise<T> {
  const res = await fetch(path)
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
  return res.json()
}

export const getSummary = () => get<Summary>('/api/summary')
export const getGLSpend = () => get<GLSpendItem[]>('/api/gl-spend')
export const getItemsPerGL = () => get<ItemsPerGLEntry[]>('/api/items-per-gl')
export const getItemsPerProperty = () => get<ItemsPerPropertyEntry[]>('/api/items-per-property')
export const getMismatches = () => get<MismatchItem[]>('/api/mismatches')
export const getNeedsReview = () => get<NeedsReviewItem[]>('/api/needs-review')

export function getInvoices(params: {
  property?: string
  gl?: number
  search?: string
  page?: number
  page_size?: number
}) {
  const qs = new URLSearchParams()
  if (params.property) qs.set('property', params.property)
  if (params.gl != null) qs.set('gl', String(params.gl))
  if (params.search) qs.set('search', params.search)
  if (params.page != null) qs.set('page', String(params.page))
  if (params.page_size != null) qs.set('page_size', String(params.page_size))
  return get<PaginatedInvoices>(`/api/invoices?${qs}`)
}

export function getInvoice(invoiceNumber: string) {
  return get<InvoiceDetail>(`/api/invoices/${encodeURIComponent(invoiceNumber)}`)
}
