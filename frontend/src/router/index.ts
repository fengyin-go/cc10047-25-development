import { createRouter, createWebHistory } from 'vue-router'

import Overview from '@/views/Overview.vue'
import WorkbenchView from '@/views/WorkbenchView.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'overview', component: Overview },
    { path: '/partition-rewrite-reconciliation', redirect: '/partition_merge?scope=RCV-M41-P3-P4' },
    { path: '/partition-rewrite-reconciliations', redirect: '/partition_merge?scope=RCV-M41-P3-P4' },
    { path: '/partition_rewrite_reconciliation', redirect: '/partition_merge?scope=RCV-M41-P3-P4' },
    { path: '/partition_rewrite_reconciliations', redirect: '/partition_merge?scope=RCV-M41-P3-P4' },
    { path: '/partition_rewrite_check', redirect: '/partition_merge?scope=RCV-M41-P3-P4' },
    { path: '/partition_reconciliation', redirect: '/partition_merge?scope=RCV-M41-P3-P4' },
    { path: '/partition_merge/reconciliation', redirect: '/partition_merge?scope=RCV-M41-P3-P4' },
    { path: '/reconciliation', redirect: '/partition_merge?scope=RCV-M41-P3-P4' },
    { path: '/snapshot-publications', redirect: '/snapshot_mgr' },
    { path: '/snapshot_publications', redirect: '/snapshot_mgr' },
    { path: '/snapshot_mgr/publications', redirect: '/snapshot_mgr' },
    { path: '/:moduleKey', name: 'module', component: WorkbenchView, props: true },
    { path: '/:pathMatch(.*)*', redirect: '/' },
  ],
})

export default router
