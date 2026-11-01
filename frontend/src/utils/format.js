const dateTime = new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'medium' })
const timeOnly = new Intl.DateTimeFormat(undefined, { timeStyle: 'medium' })

export function formatDateTime(value) {
  return value ? dateTime.format(new Date(value)) : '—'
}

export function formatTime(value) {
  return value ? timeOnly.format(new Date(value)) : '—'
}

export function shortId(id) {
  return String(id).slice(0, 8)
}

export function formatBytes(bytes) {
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

export function capitalize(text) {
  return text ? text[0].toUpperCase() + text.slice(1) : ''
}

export function listToText(list) {
  return (list ?? []).join('\n')
}

export function textToList(text) {
  return (text ?? '')
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean)
}

export function blankToNull(value) {
  const text = typeof value === 'string' ? value.trim() : value
  return text === '' || text === undefined ? null : text
}
