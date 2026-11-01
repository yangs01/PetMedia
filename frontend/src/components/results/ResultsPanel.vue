<script setup>
import { computed, ref, watch } from 'vue'

import { absoluteUrl } from '@/api/client'
import ValidationReport from '@/components/review/ValidationReport.vue'
import { capitalize, formatBytes, formatDateTime } from '@/utils/format'

import MasterCopyView from './MasterCopyView.vue'

const props = defineProps({
  task: { type: Object, required: true },
  versions: { type: Array, default: () => [] },
  assetHistory: { type: Array, default: () => [] },
  exportsList: { type: Object, default: null },
})

const active = ref(null)

const approvedVersion = computed(
  () => props.versions.find((version) => version.id === props.task.approved_version_id) ?? props.task.current_version,
)
const channel = (platform) => props.task.channel_contents.find((item) => item.platform === platform)
const instagram = computed(() => channel('instagram'))
const facebook = computed(() => channel('facebook'))
const currentAssets = computed(() => [...props.task.assets].sort((a, b) => a.slide_number - b.slide_number))
const earlierAssets = computed(() => props.assetHistory.filter((asset) => asset.status === 'SUPERSEDED'))
const hasMock = computed(
  () =>
    props.task.assets.some((asset) => asset.is_mock) ||
    approvedVersion.value?.provider === 'mock' ||
    props.task.channel_contents.some((item) => item.provider === 'mock'),
)

const tabs = computed(() => {
  const list = []
  if (approvedVersion.value) list.push({ id: 'copy', label: 'Copy' })
  if (instagram.value) list.push({ id: 'instagram', label: 'Instagram' })
  if (facebook.value) list.push({ id: 'facebook', label: 'Facebook' })
  if (props.task.carousel_plan) list.push({ id: 'carousel', label: 'Carousel' })
  if (props.exportsList?.ready) list.push({ id: 'download', label: 'Download' })
  return list
})

const completePackage = computed(() => props.exportsList?.exports.find((option) => option.name === 'all' && option.available))

const EXPORT_LABELS = {
  all: 'Complete package',
  instagram: 'Instagram package',
  facebook: 'Facebook package',
}

watch(
  tabs,
  (list) => {
    if (!list.some((tab) => tab.id === active.value)) active.value = list[0]?.id ?? null
  },
  { immediate: true },
)

function planFor(slideNumber) {
  return props.task.carousel_plan?.find((slide) => slide.slide_number === slideNumber)
}
</script>

<template>
  <section v-if="tabs.length" class="card">
    <div class="card__title">
      <h2>Generated content</h2>
      <div class="row">
        <span v-if="hasMock" class="tag mock">Mock content: do not publish</span>
        <a v-if="completePackage" :href="absoluteUrl(completePackage.url)" class="button button--primary button--small" download>
          Download ZIP
        </a>
      </div>
    </div>

    <div class="tabs" role="tablist" aria-label="Generated content">
      <button
        v-for="tab in tabs"
        :key="tab.id"
        type="button"
        role="tab"
        class="tab"
        :class="{ 'tab--active': active === tab.id }"
        :aria-selected="active === tab.id"
        @click="active = tab.id"
      >
        {{ tab.label }}
      </button>
    </div>

    <div class="tab-body fade-in" role="tabpanel">
      <template v-if="active === 'copy' && approvedVersion">
        <p class="small muted panel-note">
          Version {{ approvedVersion.version_number }} · {{ approvedVersion.provider }} ·
          {{ formatDateTime(approvedVersion.created_at) }}
        </p>
        <MasterCopyView :content="approvedVersion.content" />
        <details v-if="versions.length > 1" class="small history">
          <summary>All versions ({{ versions.length }})</summary>
          <ul class="history__list">
            <li v-for="version in versions" :key="version.id">
              <details>
                <summary>
                  v{{ version.version_number }} · {{ version.generation_source.replaceAll('_', ' ').toLowerCase() }} ·
                  {{ version.approval_status.replaceAll('_', ' ').toLowerCase() }} · {{ version.provider }}
                </summary>
                <p v-if="version.revision_feedback" class="muted">Written from: {{ version.revision_feedback }}</p>
                <ValidationReport :report="version.validation" />
                <MasterCopyView :content="version.content" class="history__copy" />
              </details>
            </li>
          </ul>
        </details>
      </template>

      <template v-else-if="active === 'instagram' && instagram">
        <p class="small muted panel-note">Provider: {{ instagram.provider }}</p>
        <p class="prose">{{ instagram.payload.caption }}</p>
        <p class="panel-gap"><strong>{{ instagram.payload.call_to_action }}</strong></p>
        <p class="hashtags">{{ instagram.payload.hashtags.join(' ') }}</p>
        <ValidationReport :report="instagram.validation" class="panel-gap" />
      </template>

      <template v-else-if="active === 'facebook' && facebook">
        <p class="small muted panel-note">Provider: {{ facebook.provider }}</p>
        <p class="prose">{{ facebook.payload.post_text }}</p>
        <p class="panel-gap"><strong>{{ facebook.payload.call_to_action }}</strong></p>
        <ValidationReport :report="facebook.validation" class="panel-gap" />
      </template>

      <template v-else-if="active === 'carousel'">
        <p v-if="!currentAssets.length" class="muted small">Slides are planned. Images are not ready yet.</p>
        <div class="slides">
          <figure v-for="asset in currentAssets" :key="asset.id" class="slide">
            <a :href="absoluteUrl(asset.url)" target="_blank" rel="noopener">
              <img
                :src="absoluteUrl(asset.url)"
                :alt="planFor(asset.slide_number)?.alt_text ?? `Slide ${asset.slide_number}`"
                :width="asset.width"
                :height="asset.height"
                class="slide__image"
                loading="lazy"
              />
            </a>
            <figcaption class="small">
              <strong>Slide {{ asset.slide_number }}</strong>
              <span class="muted"> · v{{ asset.asset_version }} · {{ formatBytes(asset.file_size) }}</span>
              <div class="muted">{{ planFor(asset.slide_number)?.alt_text }}</div>
              <div v-if="asset.visual_feedback" class="muted">Direction: {{ asset.visual_feedback }}</div>
            </figcaption>
          </figure>
        </div>
        <details v-if="earlierAssets.length" class="small history">
          <summary>Earlier image versions ({{ earlierAssets.length }})</summary>
          <div class="slides history__slides">
            <figure v-for="asset in earlierAssets" :key="asset.id" class="slide">
              <img
                :src="absoluteUrl(asset.url)"
                :alt="`Slide ${asset.slide_number}, version ${asset.asset_version}`"
                :width="asset.width"
                :height="asset.height"
                class="slide__image"
                loading="lazy"
              />
              <figcaption class="muted">Slide {{ asset.slide_number }} · v{{ asset.asset_version }}</figcaption>
            </figure>
          </div>
        </details>
      </template>

      <template v-else-if="active === 'download'">
        <p class="small muted panel-note">ZIP packages with captions, images and provenance data.</p>
        <div class="downloads">
          <a
            v-for="option in exportsList.exports"
            :key="option.name"
            :href="absoluteUrl(option.url)"
            class="button"
            :class="{ 'button--primary': option.name === 'all' }"
            download
          >
            Download {{ EXPORT_LABELS[option.name] ?? capitalize(option.name) }}
          </a>
        </div>
      </template>
    </div>
  </section>
</template>

<style scoped>
.tabs {
  display: flex;
  flex-wrap: wrap;
  gap: 2px;
  border-bottom: 1px solid var(--border);
}

.tab {
  padding: 7px 13px;
  border: 0;
  border-bottom: 2px solid transparent;
  background: none;
  color: var(--text-muted);
  font: inherit;
  font-size: 0.9rem;
  font-weight: 550;
  cursor: pointer;
}

.tab:hover {
  color: var(--text);
}

.tab--active {
  border-bottom-color: var(--accent);
  color: var(--text);
}

.tab-body {
  padding-top: 14px;
  overflow-wrap: anywhere;
}

.panel-note {
  margin-bottom: 10px;
}

.panel-gap {
  margin-top: 10px;
}

.hashtags {
  margin-top: 8px;
  color: var(--accent-strong);
  font-size: 0.9rem;
}

.mock {
  background: var(--waiting-soft);
  color: var(--waiting);
}

.slides {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
  gap: 14px;
}

.slide {
  margin: 0;
}

.slide__image {
  width: 100%;
  height: auto;
  margin-bottom: 6px;
  border-radius: 4px;
  background: var(--surface-2);
}

.history {
  margin-top: 16px;
}

.history__list {
  display: grid;
  gap: 6px;
  margin: 8px 0 0;
  padding: 0;
  list-style: none;
}

.history__copy {
  margin-top: 8px;
}

.history__slides {
  margin-top: 10px;
}

.downloads {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}
</style>
