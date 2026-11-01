const BASE_URL = (import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000').replace(/\/+$/, '')

export class ApiError extends Error {
  constructor(message, { status = 0, code = 'NETWORK_ERROR', details = {} } = {}) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.details = details
  }
}

/** Turn a path the API returned, such as /api/v1/assets/{id}, into a full URL. */
export function absoluteUrl(path) {
  return `${BASE_URL}${path}`
}

function describeError(body, status) {
  const error = body?.error
  if (!error) return `The server returned HTTP ${status}.`
  const fieldProblems = (error.details?.errors ?? []).map((item) => {
    const field = item.location.filter((part) => part !== 'body').join('.')
    return field ? `${field}: ${item.message}` : item.message
  })
  return fieldProblems.length ? fieldProblems.join(' · ') : error.message
}

async function request(path, { method = 'GET', json, formData } = {}) {
  const options = { method }
  if (json !== undefined) {
    options.headers = { 'Content-Type': 'application/json' }
    options.body = JSON.stringify(json)
  } else if (formData) {
    options.body = formData
  }

  let response
  try {
    response = await fetch(`${BASE_URL}/api/v1${path}`, options)
  } catch {
    throw new ApiError(`Cannot reach the API at ${BASE_URL}. Check that the backend is running.`)
  }

  if (response.status === 204) return null
  const body = await response.json().catch(() => null)
  if (!response.ok) {
    throw new ApiError(describeError(body, response.status), {
      status: response.status,
      code: body?.error?.code ?? `HTTP_${response.status}`,
      details: body?.error?.details ?? {},
    })
  }
  return body
}

function imageForm(file) {
  const formData = new FormData()
  formData.append('file', file)
  return formData
}

export const api = {
  health: () => request('/health/ready'),

  listBrands: () => request('/brands?limit=200'),
  getBrand: (id) => request(`/brands/${id}`),
  createBrand: (json) => request('/brands', { method: 'POST', json }),
  updateBrand: (id, json) => request(`/brands/${id}`, { method: 'PATCH', json }),
  uploadBrandLogo: (id, file) => request(`/brands/${id}/logo`, { method: 'POST', formData: imageForm(file) }),

  listProducts: () => request('/products?limit=200'),
  getProduct: (id) => request(`/products/${id}`),
  createProduct: (json) => request('/products', { method: 'POST', json }),
  updateProduct: (id, json) => request(`/products/${id}`, { method: 'PATCH', json }),
  archiveProduct: (id) => request(`/products/${id}`, { method: 'DELETE' }),
  listProductImages: (id) => request(`/products/${id}/images`),
  uploadProductImage: (id, file) =>
    request(`/products/${id}/images`, { method: 'POST', formData: imageForm(file) }),
  listReviews: (id) => request(`/products/${id}/reviews`),
  createReview: (id, json) => request(`/products/${id}/reviews`, { method: 'POST', json }),

  listTasks: () => request('/tasks?limit=200'),
  getTask: (id) => request(`/tasks/${id}`),
  createTask: (json) => request('/tasks', { method: 'POST', json }),
  retryTask: (id) => request(`/tasks/${id}/retry`, { method: 'POST' }),
  cancelTask: (id) => request(`/tasks/${id}/cancel`, { method: 'POST' }),
  listEvents: (id, afterId) => request(`/tasks/${id}/events?after_id=${afterId}&limit=500`),
  listTopics: (id) => request(`/tasks/${id}/topics`),
  listVersions: (id) => request(`/tasks/${id}/versions`),
  listAssetHistory: (id) => request(`/tasks/${id}/assets?include_history=true`),
  listExports: (id) => request(`/tasks/${id}/exports`),

  decideTopic: (id, json) => request(`/tasks/${id}/topic-decision`, { method: 'POST', json }),
  decideCopy: (id, json) => request(`/tasks/${id}/copy-decision`, { method: 'POST', json }),
  decideImages: (id, json) => request(`/tasks/${id}/image-decision`, { method: 'POST', json }),
}
