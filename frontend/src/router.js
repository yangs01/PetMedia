import { createRouter, createWebHistory } from 'vue-router'

import CatalogView from './views/CatalogView.vue'
import CreateTaskView from './views/CreateTaskView.vue'
import DashboardView from './views/DashboardView.vue'
import NotFoundView from './views/NotFoundView.vue'
import TaskView from './views/TaskView.vue'

export default createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'dashboard', component: DashboardView },
    { path: '/create', name: 'create', component: CreateTaskView },
    { path: '/catalog', name: 'catalog', component: CatalogView },
    { path: '/tasks/:id', name: 'task', component: TaskView, props: true },
    { path: '/:pathMatch(.*)*', name: 'not-found', component: NotFoundView },
  ],
})
