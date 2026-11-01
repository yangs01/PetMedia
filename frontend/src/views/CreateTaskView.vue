<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'

import { api } from '@/api/client'
import BrandForm from '@/components/catalog/BrandForm.vue'
import ProductForm from '@/components/catalog/ProductForm.vue'
import ErrorBanner from '@/components/common/ErrorBanner.vue'
import LoadingBlock from '@/components/common/LoadingBlock.vue'
import { blankToNull } from '@/utils/format'

const router = useRouter()

const CHANNELS = ['instagram', 'facebook']
const MAX_PRODUCTS = 10

const brands = ref([])
const products = ref([])
const loading = ref(true)
const loadError = ref('')
const submitError = ref('')
const submitting = ref(false)
const addingBrand = ref(false)
const addingProduct = ref(false)

const form = reactive({
  brand_id: '',
  product_ids: [],
  target_market: '',
  target_audience: '',
  marketing_goal: '',
  operator_instructions: '',
  channels: [...CHANNELS],
  image_count: '',
  target_word_count: '',
})

const selectedBrand = computed(() => brands.value.find((brand) => brand.id === form.brand_id))

const missing = computed(() => {
  const problems = []
  if (!form.brand_id) problems.push('a brand')
  if (!form.product_ids.length) problems.push('at least one product')
  if (!form.channels.length) problems.push('a channel')
  return problems
})

async function load() {
  loading.value = true
  loadError.value = ''
  try {
    const [brandList, productList] = await Promise.all([api.listBrands(), api.listProducts()])
    brands.value = brandList
    products.value = productList
    if (brandList.length === 1) form.brand_id = brandList[0].id
  } catch (problem) {
    loadError.value = problem.message
  } finally {
    loading.value = false
  }
}

function brandSaved(brand) {
  brands.value.unshift(brand)
  form.brand_id = brand.id
  addingBrand.value = false
}

function productSaved(product) {
  products.value.unshift(product)
  if (form.product_ids.length < MAX_PRODUCTS) form.product_ids.push(product.id)
  addingProduct.value = false
}

async function submit() {
  submitting.value = true
  submitError.value = ''
  try {
    const created = await api.createTask({
      brand_id: form.brand_id,
      product_ids: form.product_ids,
      target_market: blankToNull(form.target_market),
      target_audience: blankToNull(form.target_audience),
      marketing_goal: blankToNull(form.marketing_goal),
      operator_instructions: blankToNull(form.operator_instructions),
      channels: form.channels,
      image_count: form.image_count === '' ? null : Number(form.image_count),
      target_word_count: form.target_word_count === '' ? null : Number(form.target_word_count),
    })
    router.push({ name: 'task', params: { id: created.task_id } })
  } catch (problem) {
    submitError.value = problem.message
  } finally {
    submitting.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="page page--narrow">
    <header class="page__header">
      <div>
        <h1>New content task</h1>
        <p class="page__sub">Choose what to promote, then start the agent. You approve each stage.</p>
      </div>
    </header>

    <LoadingBlock v-if="loading" />
    <ErrorBanner v-else-if="loadError" title="Could not load brands and products" :message="loadError" action-label="Try again" @action="load" />

    <!-- The brand and product forms are not nested in the task form, because forms cannot nest. -->
    <div v-else>
      <section class="card">
        <div class="card__title">
          <h2>1. Brand</h2>
          <button type="button" class="button button--small" @click="addingBrand = !addingBrand">
            {{ addingBrand ? 'Hide form' : 'Add brand' }}
          </button>
        </div>
        <BrandForm v-if="addingBrand" class="inline-form fade-in" @saved="brandSaved" @close="addingBrand = false" />
        <p v-if="!brands.length && !addingBrand" class="small muted">No brands yet. Add one to continue.</p>
        <div v-if="brands.length" class="field">
          <label class="field__label" for="task-brand">Brand</label>
          <select id="task-brand" v-model="form.brand_id" class="select" required>
            <option value="" disabled>Choose a brand</option>
            <option v-for="brand in brands" :key="brand.id" :value="brand.id">{{ brand.brand_name }}</option>
          </select>
          <span v-if="selectedBrand?.brand_description" class="field__hint">{{ selectedBrand.brand_description }}</span>
        </div>
      </section>

      <section class="card">
        <div class="card__title">
          <h2>2. Products</h2>
          <button type="button" class="button button--small" @click="addingProduct = !addingProduct">
            {{ addingProduct ? 'Hide form' : 'Add product' }}
          </button>
        </div>
        <ProductForm v-if="addingProduct" class="inline-form fade-in" @saved="productSaved" @close="addingProduct = false" />
        <p v-if="!products.length && !addingProduct" class="small muted">No products yet. Add one to continue.</p>
        <div class="products">
          <label
            v-for="product in products"
            :key="product.id"
            class="product"
            :class="{ 'product--selected': form.product_ids.includes(product.id) }"
          >
            <input
              v-model="form.product_ids"
              type="checkbox"
              :value="product.id"
              :disabled="form.product_ids.length >= MAX_PRODUCTS && !form.product_ids.includes(product.id)"
            />
            <span class="product__text">
              <strong>{{ product.name }}</strong>
              <span class="small muted">{{ product.category }}</span>
            </span>
          </label>
        </div>
      </section>

      <form @submit.prevent="submit">
      <section class="card requirements">
        <div class="card__title"><h2>3. Requirements</h2></div>
        <div class="form-grid">
          <div class="field">
            <label class="field__label" for="task-market">Target market</label>
            <input id="task-market" v-model="form.target_market" class="input" maxlength="50" placeholder="Default: US" />
          </div>
          <div class="field">
            <label class="field__label" for="task-audience">Target audience</label>
            <input id="task-audience" v-model="form.target_audience" class="input" maxlength="2000" placeholder="First-time cat owners" />
          </div>
          <div class="field form-grid__wide">
            <label class="field__label" for="task-goal">Marketing goal</label>
            <input id="task-goal" v-model="form.marketing_goal" class="input" maxlength="2000" placeholder="Brand awareness" />
          </div>
          <div class="field form-grid__wide">
            <label class="field__label" for="task-instructions">Instructions for the agent</label>
            <textarea id="task-instructions" v-model="form.operator_instructions" class="textarea" maxlength="5000" placeholder="Focus on indoor cats." />
          </div>
          <div class="field">
            <label class="field__label" for="task-images">Carousel slides</label>
            <select id="task-images" v-model="form.image_count" class="select">
              <option value="">Default (4)</option>
              <option v-for="count in [3, 4, 5]" :key="count" :value="count">{{ count }}</option>
            </select>
          </div>
          <div class="field">
            <label class="field__label" for="task-words">Target word count</label>
            <input id="task-words" v-model="form.target_word_count" class="input" type="number" min="100" max="2000" placeholder="Default: 700" />
          </div>
          <fieldset class="channels form-grid__wide">
            <legend class="field__label">Channels</legend>
            <label v-for="channel in CHANNELS" :key="channel" class="check channel">
              <input v-model="form.channels" type="checkbox" :value="channel" />
              {{ channel }}
            </label>
          </fieldset>
        </div>
      </section>

      <ErrorBanner v-if="submitError" class="submit-error" title="The task was not created" :message="submitError" />

      <div class="row submit">
        <button type="submit" class="button button--primary" :disabled="submitting || missing.length > 0">
          {{ submitting ? 'Starting…' : 'Start AI workflow' }}
        </button>
        <span v-if="missing.length" class="small muted">Choose {{ missing.join(', ') }} to continue.</span>
      </div>
      </form>
    </div>
  </div>
</template>

<style scoped>
.requirements {
  margin-top: 16px;
}

.inline-form {
  margin-bottom: 14px;
  padding: 14px;
  background: var(--surface-2);
  border-radius: var(--radius-small);
}

.products {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 8px;
}

.product {
  display: flex;
  gap: 10px;
  padding: 10px 12px;
  border: 1px solid var(--border);
  border-radius: var(--radius-small);
  cursor: pointer;
  transition:
    border-color 0.15s,
    background-color 0.15s;
}

.product--selected {
  border-color: var(--accent);
  background: var(--accent-soft);
}

.product input {
  flex: none;
  align-self: flex-start;
  margin-top: 3px;
  accent-color: var(--accent);
}

.product__text {
  display: grid;
  min-width: 0;
  overflow-wrap: anywhere;
}

.channels {
  display: flex;
  flex-wrap: wrap;
  gap: 6px 20px;
  margin: 0;
  padding: 0;
  border: 0;
}

.channels legend {
  padding: 0;
  margin-bottom: 4px;
}

.channel {
  text-transform: capitalize;
}

.submit-error {
  margin-top: 16px;
}

.submit {
  margin-top: 16px;
}
</style>
