<script setup>
import { computed, onMounted, ref } from 'vue'

import { absoluteUrl, api } from '@/api/client'
import BrandForm from '@/components/catalog/BrandForm.vue'
import ProductForm from '@/components/catalog/ProductForm.vue'
import ProductReviews from '@/components/catalog/ProductReviews.vue'
import ConfirmButton from '@/components/common/ConfirmButton.vue'
import EmptyState from '@/components/common/EmptyState.vue'
import ErrorBanner from '@/components/common/ErrorBanner.vue'
import LoadingBlock from '@/components/common/LoadingBlock.vue'

const brands = ref([])
const products = ref([])
const images = ref({})
const loading = ref(true)
const error = ref('')
// Which form is open: 'new', an id, or null.
const editingBrand = ref(null)
const editingProduct = ref(null)

const currentBrand = computed(() => brands.value.find((brand) => brand.id === editingBrand.value) ?? null)
const currentProduct = computed(() => products.value.find((product) => product.id === editingProduct.value) ?? null)

async function loadImages(product) {
  try {
    images.value = { ...images.value, [product.id]: await api.listProductImages(product.id) }
  } catch {
    // A missing thumbnail does not stop the catalog from working.
  }
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    const [brandList, productList] = await Promise.all([api.listBrands(), api.listProducts()])
    brands.value = brandList
    products.value = productList
    productList.forEach(loadImages)
  } catch (problem) {
    error.value = problem.message
  } finally {
    loading.value = false
  }
}

function brandSaved(saved) {
  const index = brands.value.findIndex((brand) => brand.id === saved.id)
  if (index >= 0) brands.value[index] = saved
  else brands.value.unshift(saved)
  editingBrand.value = null
}

function productSaved(saved) {
  const index = products.value.findIndex((product) => product.id === saved.id)
  if (index >= 0) products.value[index] = saved
  else products.value.unshift(saved)
  loadImages(saved)
  if (editingProduct.value === 'new') editingProduct.value = null
}

async function archive(product) {
  error.value = ''
  try {
    await api.archiveProduct(product.id)
    products.value = products.value.filter((item) => item.id !== product.id)
    editingProduct.value = null
  } catch (problem) {
    error.value = problem.message
  }
}

onMounted(load)
</script>

<template>
  <div class="page">
    <header class="page__header">
      <div>
        <h1>Brands &amp; products</h1>
        <p class="page__sub">The facts the agent is allowed to use.</p>
      </div>
    </header>

    <ErrorBanner v-if="error" class="catalog-error" :message="error" action-label="Try again" @action="load" />
    <LoadingBlock v-if="loading" />

    <div v-else class="catalog">
      <section class="card">
        <div class="card__title">
          <h2>Brands</h2>
          <button type="button" class="button button--small" @click="editingBrand = 'new'">Add brand</button>
        </div>
        <BrandForm
          v-if="editingBrand === 'new'"
          class="inline-form fade-in"
          @saved="brandSaved"
          @close="editingBrand = null"
        />
        <EmptyState v-if="!brands.length && editingBrand !== 'new'" title="No brands yet" />
        <ul class="items">
          <li v-for="brand in brands" :key="brand.id" class="item">
            <div class="row row--between">
              <div class="item__text">
                <strong>{{ brand.brand_name }}</strong>
                <div class="small muted">{{ brand.brand_voice.join(', ') || 'No brand voice set' }}</div>
              </div>
              <button
                type="button"
                class="button button--small"
                @click="editingBrand = editingBrand === brand.id ? null : brand.id"
              >
                {{ editingBrand === brand.id ? 'Close' : 'Edit' }}
              </button>
            </div>
            <BrandForm
              v-if="editingBrand === brand.id"
              :key="brand.updated_at"
              :brand="currentBrand"
              class="inline-form fade-in"
              @saved="brandSaved"
              @close="editingBrand = null"
            />
          </li>
        </ul>
      </section>

      <section class="card">
        <div class="card__title">
          <h2>Products</h2>
          <button type="button" class="button button--small" @click="editingProduct = 'new'">Add product</button>
        </div>
        <ProductForm
          v-if="editingProduct === 'new'"
          class="inline-form fade-in"
          @saved="productSaved"
          @close="editingProduct = null"
        />
        <EmptyState v-if="!products.length && editingProduct !== 'new'" title="No products yet" />
        <ul class="items">
          <li v-for="product in products" :key="product.id" class="item">
            <div class="row row--between">
              <div class="row item__text">
                <img
                  v-if="images[product.id]?.length"
                  :src="absoluteUrl(images[product.id][0].url)"
                  alt=""
                  class="thumb"
                  width="44"
                  height="44"
                />
                <span v-else class="thumb thumb--empty small muted">No photo</span>
                <div class="item__text">
                  <strong>{{ product.name }}</strong>
                  <div class="small muted">{{ product.category }}</div>
                </div>
              </div>
              <button
                type="button"
                class="button button--small"
                @click="editingProduct = editingProduct === product.id ? null : product.id"
              >
                {{ editingProduct === product.id ? 'Close' : 'Edit' }}
              </button>
            </div>
            <div v-if="editingProduct === product.id" class="stack inline-form fade-in">
              <ProductForm
                :key="product.updated_at"
                :product="currentProduct"
                @saved="productSaved"
                @close="editingProduct = null"
              />
              <ProductReviews :product-id="product.id" />
              <div class="archive">
                <ConfirmButton
                  label="Archive product"
                  question="Archive it? Existing tasks keep their history."
                  confirm-label="Yes, archive"
                  @confirm="archive(product)"
                />
              </div>
            </div>
          </li>
        </ul>
      </section>
    </div>
  </div>
</template>

<style scoped>
.catalog-error {
  margin-bottom: 14px;
}

.catalog {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  align-items: start;
  gap: 16px;
}

.catalog .card + .card {
  margin-top: 0;
}

.items {
  display: grid;
  gap: 0;
  margin: 0;
  padding: 0;
  list-style: none;
}

.item {
  padding: 11px 0;
  border-top: 1px solid var(--border);
}

.item:first-child {
  border-top: 0;
}

.item__text {
  flex: 1;
  min-width: 0;
  overflow-wrap: anywhere;
}

.item__text .item__text {
  flex-basis: 0;
}

.thumb {
  flex: none;
  width: 44px;
  height: 44px;
  border-radius: var(--radius-small);
  object-fit: cover;
}

.thumb--empty {
  display: grid;
  place-items: center;
  background: var(--surface-2);
  font-size: 0.66rem;
  line-height: 1.1;
  text-align: center;
}

.inline-form {
  margin-top: 12px;
  padding: 14px;
  background: var(--surface-2);
  border-radius: var(--radius-small);
}

.archive {
  padding-top: 10px;
  border-top: 1px solid var(--border);
}

@media (max-width: 1080px) {
  .catalog {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>
