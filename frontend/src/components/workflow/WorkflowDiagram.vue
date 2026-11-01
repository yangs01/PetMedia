<script setup>
import { computed } from 'vue'

import { FORWARD_EDGES, LOOP_EDGES, NODES, STATE_LABELS } from '@/workflow/graph'

const props = defineProps({
  workflow: { type: Object, required: true },
  selected: { type: String, default: null },
})
const emit = defineEmits(['select'])

const WIDTH = 172
const HEIGHT = 88
const COLUMNS = [8, 212, 416, 620]
const ROWS = [44, 234, 424]
const ARROW_GAP = 6
const WRAP_DROP = 50
const LOOP_RISE = 38
const LOOP_OFFSET = 36

const LEGEND = ['completed', 'running', 'waiting', 'queued', 'failed', 'cancelled', 'pending']

function box(id) {
  const node = NODES.find((item) => item.id === id)
  return { x: COLUMNS[node.col], y: ROWS[node.row], row: node.row }
}

function forwardPath(fromId, toId) {
  const from = box(fromId)
  const to = box(toId)
  if (from.row === to.row) {
    const y = from.y + HEIGHT / 2
    return `M ${from.x + WIDTH} ${y} L ${to.x - ARROW_GAP} ${y}`
  }
  const startX = from.x + WIDTH / 2
  const endX = to.x + WIDTH / 2
  const wrapY = from.y + HEIGHT + WRAP_DROP
  return `M ${startX} ${from.y + HEIGHT} V ${wrapY} H ${endX} V ${to.y - ARROW_GAP}`
}

function loopGeometry({ from: fromId, to: toId, side }) {
  const from = box(fromId)
  const to = box(toId)
  const startX = from.x + WIDTH / 2 - LOOP_OFFSET
  const endX = to.x + WIDTH / 2 + LOOP_OFFSET
  const direction = side === 'top' ? -1 : 1
  const startY = side === 'top' ? from.y : from.y + HEIGHT
  const endY = side === 'top' ? to.y - ARROW_GAP : to.y + HEIGHT + ARROW_GAP
  const controlY = startY + direction * LOOP_RISE
  return {
    path: `M ${startX} ${startY} C ${startX} ${controlY} ${endX} ${controlY} ${endX} ${endY}`,
    labelX: (startX + endX) / 2,
    labelY: startY + direction * (LOOP_RISE * 0.75) + (side === 'top' ? -4 : 12),
  }
}

const forwardEdges = computed(() =>
  FORWARD_EDGES.map(([from, to]) => {
    const toState = props.workflow.nodes[to].state
    const fromState = props.workflow.nodes[from].state
    let state = 'pending'
    if (fromState === 'completed' && toState === 'completed') state = 'done'
    else if (fromState === 'completed' && ['running', 'queued', 'waiting'].includes(toState)) state = 'active'
    else if (fromState === 'completed') state = 'done'
    return { key: `${from}>${to}`, path: forwardPath(from, to), state }
  }),
)

const loopEdges = computed(() =>
  LOOP_EDGES.map((edge) => ({
    ...edge,
    ...loopGeometry(edge),
    key: `${edge.from}>${edge.to}`,
    ran: props.workflow.loops[`${edge.from}>${edge.to}`],
  })),
)

const nodes = computed(() =>
  NODES.map((node) => ({
    ...props.workflow.nodes[node.id],
    x: COLUMNS[node.col],
    y: ROWS[node.row],
    label: STATE_LABELS[props.workflow.nodes[node.id].state],
  })),
)

function truncate(text, limit) {
  if (!text) return ''
  return text.length > limit ? `${text.slice(0, limit - 1)}…` : text
}

</script>

<template>
  <div class="diagram-scroll">
    <svg class="diagram" viewBox="0 0 800 520" role="group" aria-label="Workflow graph">
      <defs>
        <marker
          v-for="name in ['pending', 'done', 'active', 'loop', 'loop-ran']"
          :id="`arrow-${name}`"
          :key="name"
          viewBox="0 0 10 10"
          refX="8"
          refY="5"
          markerWidth="7"
          markerHeight="7"
          orient="auto-start-reverse"
        >
          <path d="M 0 1 L 9 5 L 0 9 z" :class="`arrow arrow--${name}`" />
        </marker>
      </defs>

      <path
        v-for="edge in forwardEdges"
        :key="edge.key"
        :d="edge.path"
        class="edge"
        :class="`edge--${edge.state}`"
        :marker-end="`url(#arrow-${edge.state})`"
      />

      <g v-for="edge in loopEdges" :key="edge.key">
        <path
          :d="edge.path"
          class="loop"
          :class="{ 'loop--ran': edge.ran }"
          :marker-end="`url(#arrow-${edge.ran ? 'loop-ran' : 'loop'})`"
        />
        <text :x="edge.labelX" :y="edge.labelY" class="loop__label" :class="{ 'loop__label--ran': edge.ran }">
          {{ edge.label }}
        </text>
      </g>

      <g
        v-for="node in nodes"
        :key="node.id"
        class="node"
        :class="[`node--${node.state}`, `node--${node.kind}`, { 'node--selected': selected === node.id }]"
        :transform="`translate(${node.x} ${node.y})`"
        role="button"
        tabindex="0"
        :aria-label="`${node.title}: ${node.label}. ${node.detail}`"
        :aria-pressed="selected === node.id"
        @click="emit('select', node.id)"
        @keydown.enter.prevent="emit('select', node.id)"
        @keydown.space.prevent="emit('select', node.id)"
      >
        <rect class="node__body" :width="WIDTH" :height="HEIGHT" rx="10" />
        <rect v-if="node.state === 'running'" class="node__pulse" :width="WIDTH" :height="HEIGHT" rx="10" />

        <g class="node__icon" transform="translate(21 22)">
          <circle r="10" class="node__icon-bg" />
          <path v-if="node.state === 'completed'" d="M -4.5 0 L -1.2 3.4 L 4.6 -3.4" class="icon-stroke" />
          <path v-else-if="node.state === 'running'" d="M 0 -5.5 A 5.5 5.5 0 1 1 -5.5 0" class="icon-stroke icon-spin" />
          <path v-else-if="node.state === 'waiting'" d="M -2.5 -4.5 V 4.5 M 2.5 -4.5 V 4.5" class="icon-stroke" />
          <path v-else-if="node.state === 'failed'" d="M -4 -4 L 4 4 M 4 -4 L -4 4" class="icon-stroke" />
          <path v-else-if="node.state === 'queued'" d="M 0 -5 V 0 L 3.5 2.5" class="icon-stroke" />
          <path v-else-if="node.state === 'cancelled'" d="M -4.5 0 H 4.5" class="icon-stroke" />
          <circle v-else r="2.5" class="icon-dot" />
        </g>

        <text x="38" y="20" class="node__title">{{ node.title }}</text>
        <text x="38" y="36" class="node__state">{{ node.label }}</text>
        <text x="12" y="62" class="node__detail">{{ truncate(node.detail, 24) }}</text>
        <text x="12" y="78" class="node__kind">
          {{ node.kind === 'human' ? 'Human review' : node.kind === 'ai' ? truncate(node.provider || 'AI step', 24) : 'System step' }}
        </text>
      </g>
    </svg>
  </div>
  <ul class="legend small" aria-label="Node states">
    <li v-for="state in LEGEND" :key="state" class="legend__item">
      <span class="swatch" :class="`swatch--${state}`" aria-hidden="true" />
      {{ STATE_LABELS[state] }}
    </li>
  </ul>
  <p class="legend__note small muted">
    Read from the task's status, events and saved records on the backend, about every 2 seconds. Dashed arrows are
    loops, highlighted once they have run.
  </p>
</template>

<style scoped>
.diagram-scroll {
  overflow-x: auto;
}

.diagram {
  display: block;
  width: 100%;
  min-width: 580px;
  height: auto;
  font-family: var(--font);
}

.edge,
.loop {
  fill: none;
}

.edge {
  stroke-width: 2;
  stroke-linejoin: round;
  transition: stroke 0.3s;
}

.edge--pending {
  stroke: var(--border-strong);
}

.edge--done {
  stroke: var(--completed);
}

.edge--active {
  stroke: var(--running);
  stroke-dasharray: 7 5;
  animation: flow 0.9s linear infinite;
}

.arrow--pending {
  fill: var(--border-strong);
}

.arrow--done {
  fill: var(--completed);
}

.arrow--active {
  fill: var(--running);
}

.arrow--loop {
  fill: var(--border-strong);
}

.arrow--loop-ran {
  fill: var(--accent);
}

@keyframes flow {
  to {
    stroke-dashoffset: -12;
  }
}

.loop {
  stroke: var(--border-strong);
  stroke-width: 1.25;
  stroke-dasharray: 3 4;
}

.loop--ran {
  stroke: var(--accent);
  stroke-width: 1.75;
}

.loop__label {
  fill: var(--text-muted);
  font-size: 11px;
  text-anchor: middle;
}

.loop__label--ran {
  fill: var(--accent-strong);
  font-weight: 600;
}

.legend {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 14px;
  margin: 10px 0 0;
  padding: 0;
  list-style: none;
}

.legend__item {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: var(--text-muted);
}

.legend__note {
  margin-top: 4px;
}

.swatch {
  width: 13px;
  height: 13px;
  border: 1.5px solid;
  border-radius: 4px;
}

.swatch--completed {
  background: var(--completed-soft);
  border-color: var(--completed);
}

.swatch--running {
  background: var(--running-soft);
  border-color: var(--running);
}

.swatch--waiting {
  background: var(--waiting-soft);
  border-color: var(--waiting);
}

.swatch--queued {
  background: var(--queued-soft);
  border-color: var(--queued);
}

.swatch--failed {
  background: var(--failed-soft);
  border-color: var(--failed);
}

.swatch--cancelled {
  background: var(--cancelled-soft);
  border-color: var(--cancelled);
}

.swatch--pending {
  background: var(--pending-soft);
  border-color: var(--border-strong);
}

.node {
  --node: var(--pending);
  --node-soft: var(--surface);
  --node-border: var(--border-strong);

  cursor: pointer;
  outline: none;
}

.node--completed {
  --node: var(--completed);
  --node-soft: var(--completed-soft);
  --node-border: var(--completed);
}

.node--running {
  --node: var(--running);
  --node-soft: var(--running-soft);
  --node-border: var(--running);
}

.node--waiting {
  --node: var(--waiting);
  --node-soft: var(--waiting-soft);
  --node-border: var(--waiting);
}

.node--failed {
  --node: var(--failed);
  --node-soft: var(--failed-soft);
  --node-border: var(--failed);
}

.node--queued {
  --node: var(--queued);
  --node-soft: var(--queued-soft);
  --node-border: var(--queued);
}

.node--cancelled {
  --node: var(--cancelled);
  --node-soft: var(--cancelled-soft);
  --node-border: var(--cancelled);
}

.node__body {
  fill: var(--node-soft);
  stroke: var(--node-border);
  stroke-width: 1.5;
  transition:
    fill 0.3s,
    stroke 0.3s;
}

.node--human .node__body {
  stroke-dasharray: 6 3;
}

.node--waiting .node__body {
  stroke-width: 2.5;
  stroke-dasharray: none;
  animation: attention 1.6s ease-in-out infinite;
}

.node--running .node__body,
.node--failed .node__body {
  stroke-width: 2.5;
}

.node:hover .node__body {
  filter: brightness(0.97);
}

.node--selected .node__body,
.node:focus-visible .node__body {
  stroke: var(--accent);
  stroke-width: 3;
  stroke-dasharray: none;
}

.node__pulse {
  fill: none;
  stroke: var(--running);
  stroke-width: 2;
  transform-box: fill-box;
  transform-origin: center;
  animation: pulse 1.6s ease-out infinite;
  pointer-events: none;
}

@keyframes pulse {
  from {
    opacity: 0.7;
    transform: scale(1);
  }

  to {
    opacity: 0;
    transform: scale(1.09, 1.18);
  }
}

@keyframes attention {
  50% {
    stroke-opacity: 0.4;
  }
}

.node__icon-bg {
  fill: var(--surface);
  stroke: var(--node);
  stroke-width: 1.5;
}

.icon-stroke {
  fill: none;
  stroke: var(--node);
  stroke-width: 2;
  stroke-linecap: round;
  stroke-linejoin: round;
}

.icon-dot {
  fill: var(--node);
}

.icon-spin {
  transform-origin: 0 0;
  animation: spin 1s linear infinite;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

.node__title {
  fill: var(--text);
  font-size: 15px;
  font-weight: 650;
}

.node__state {
  fill: var(--node);
  font-size: 13px;
  font-weight: 600;
}

.node__detail {
  fill: var(--text);
  font-size: 13px;
}

.node__kind {
  fill: var(--text-muted);
  font-size: 12px;
}

.node--pending .node__title,
.node--pending .node__detail {
  fill: var(--text-muted);
}
</style>
