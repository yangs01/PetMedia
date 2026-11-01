<script setup>
defineProps({
  content: { type: Object, required: true },
})
</script>

<template>
  <article class="copy">
    <h3 class="copy__title">{{ content.title }}</h3>
    <p class="copy__hook">{{ content.opening_hook }}</p>
    <p class="prose copy__body">{{ content.body }}</p>
    <h4 class="copy__subhead">Key takeaways</h4>
    <ul class="copy__list">
      <li v-for="item in content.key_takeaways" :key="item">{{ item }}</li>
    </ul>
    <h4 class="copy__subhead">Call to action</h4>
    <p>{{ content.call_to_action }}</p>
  </article>
</template>

<style scoped>
.copy {
  max-width: 72ch;
  overflow-wrap: anywhere;
}

.copy__title {
  font-size: 1.15rem;
  line-height: 1.3;
}

.copy__hook {
  margin-top: 6px;
  font-weight: 550;
}

.copy__body {
  margin-top: 10px;
}

.copy__subhead {
  margin-top: 14px;
  font-size: 0.85rem;
}

.copy__list {
  margin: 4px 0 0;
  padding-left: 20px;
}
</style>
