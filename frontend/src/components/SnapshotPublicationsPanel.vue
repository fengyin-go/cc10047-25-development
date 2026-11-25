<template>
  <section class="pub-panel" data-testid="snapshot-publication-checklist">
    <div class="pub-head">
      <div>
        <h3>快照发布清单</h3>
        <p>分区重写核对结论同步；从核对视图登记的快照会展示采用范围、k5 可读值和未结记录。</p>
      </div>
      <button class="btn" type="button" data-testid="refresh-publications" @click="load()">刷新清单</button>
    </div>

    <p v-if="errorMessage" class="error-text" role="alert">{{ errorMessage }}</p>
    <p v-if="!loading && !publications.length" class="empty-pub" data-testid="publication-empty">
      暂无分区重写核对发布快照；可前往「分区合并 → 分区重写核对视图」登记。
      <RouterLink class="btn primary" to="/partition_merge?scope=RCV-M41-P3-P4">打开 M41 核对视图</RouterLink>
    </p>

    <div class="pub-list" data-testid="publication-list">
      <article
        v-for="pub in publications"
        :key="pub.publication_id"
        class="pub-card"
        :data-testid="`publication-${pub.task_code}`"
        :data-publication-id="pub.publication_id"
      >
        <header>
          <div>
            <h4>{{ pub.snapshot_id }}</h4>
            <p>{{ pub.task_code }}：{{ pub.source_partition }} → {{ pub.target_partition }} ｜ {{ pub.table_name }}</p>
          </div>
          <span class="release-version" data-testid="checklist-release-version">{{ pub.release_version }}</span>
        </header>

        <div class="pub-grid">
          <div>
            <span>发布版本 / 核对版本</span>
            <strong>{{ pub.release_version }} / <code data-testid="checklist-recon-version">{{ pub.published_version }}</code></strong>
          </div>
          <div>
            <span>本次采用范围</span>
            <strong :data-testid="`checklist-scope-mode-${pub.scope_mode}`">
              {{ pub.scope_mode === 'refreshed' ? '刷新后更正版本' : '沿用打开时范围' }}
            </strong>
          </div>
          <div>
            <span>p4 的 k5 可读值</span>
            <strong><code data-testid="checklist-p4-k5">{{ pub.p4_k5_readable_value }}</code></strong>
          </div>
          <div>
            <span>移出 / 移入 / 待核差异</span>
            <strong>{{ pub.conclusion?.actual_moved_out }} / {{ pub.conclusion?.actual_moved_in }} / {{ pub.conclusion?.pending_differences }}</strong>
          </div>
        </div>

        <p class="scope-description" data-testid="checklist-scope-description">{{ pub.published_scope_description }}</p>

        <div class="pub-actions">
          <button
            class="btn primary"
            type="button"
            :data-testid="`view-snapshot-detail-${pub.snapshot_id}`"
            @click="openDetail(pub.publication_id)"
          >
            查看快照详情
          </button>
          <RouterLink class="btn" :to="`/partition_merge?scope=${encodeURIComponent(pub.scope_id)}`">
            查看核对视图
          </RouterLink>
          <span class="pending-pill">仍待处理记录：{{ pub.pending_record_count }}</span>
        </div>
      </article>
    </div>

    <div v-if="detail" class="detail-backdrop" data-testid="snapshot-detail-modal" @click.self="closeDetail">
      <section class="detail-modal" role="dialog" aria-modal="true" data-testid="snapshot-detail">
        <header>
          <div>
            <h3>快照详情：{{ detail.snapshot_id }}</h3>
            <p>{{ detail.release_version }} ｜ 核对版本 {{ detail.published_version }}</p>
          </div>
          <button class="btn" type="button" data-testid="close-snapshot-detail" @click="closeDetail">关闭</button>
        </header>

        <section class="detail-section">
          <h4>本次采用的核对范围</h4>
          <p data-testid="detail-adoption-statement">{{ detail.adoption_statement }}</p>
          <p class="muted" data-testid="detail-scope-statement">{{ detail.scope_statement }}</p>
          <p class="muted">{{ detail.published_scope_description }}</p>
        </section>

        <section class="detail-grid">
          <div><span>任务</span><strong>{{ detail.task_code }}</strong></div>
          <div><span>源分区</span><strong>{{ detail.source_partition }}</strong></div>
          <div><span>目标分区</span><strong>{{ detail.target_partition }}</strong></div>
          <div><span>打开时来源版本</span><strong>r{{ detail.source_revision_at_open }}</strong></div>
          <div><span>发布时来源版本</span><strong>r{{ detail.source_revision_at_publish }}</strong></div>
          <div><span>p4 的 k5</span><strong><code data-testid="detail-p4-k5">{{ detail.p4_k5_readable_value }}</code></strong></div>
        </section>

        <section class="detail-section" data-testid="detail-conclusion">
          <h4>核对结论</h4>
          <div class="conclusion-row">
            <span>实际移出：<b>{{ detail.conclusion?.actual_moved_out }}</b></span>
            <span>实际移入：<b>{{ detail.conclusion?.actual_moved_in }}</b></span>
            <span>待核差异：<b>{{ detail.conclusion?.pending_differences }}</b></span>
            <span>重复移出：<b>{{ detail.conclusion?.duplicate_moved_out }}</b></span>
          </div>
        </section>

        <section class="detail-section" data-testid="detail-pending-records">
          <h4>仍待处理记录</h4>
          <table class="data-table">
            <thead><tr><th>记录</th><th>键</th><th>状态</th><th>说明</th></tr></thead>
            <tbody>
              <tr v-for="record in detail.pending_records" :key="record.id" :data-testid="`detail-pending-${record.row_key}`">
                <td>{{ record.id }}</td>
                <td>{{ record.row_key }}</td>
                <td>{{ record.status }}</td>
                <td>{{ record.message }}</td>
              </tr>
              <tr v-if="!detail.pending_records?.length"><td colspan="4" class="empty-state">没有仍待处理记录</td></tr>
            </tbody>
          </table>
        </section>

        <section class="detail-section" data-testid="detail-evidence">
          <h4>更正前后来源证据（断线恢复后仍保留）</h4>
          <article v-for="ev in detail.evidence || []" :key="ev.evidence_id" class="evidence">
            <header><strong>{{ ev.evidence_id }}</strong><span>{{ ev.kind }}</span></header>
            <p>{{ ev.partition }} / {{ ev.row_key }} / r{{ ev.revision }}</p>
            <p v-if="ev.before">更正前：<code>{{ ev.before.value }}</code>（{{ ev.before.checksum }}）</p>
            <p v-if="ev.after">更正后：<code>{{ ev.after.value }}</code>（{{ ev.after.checksum }}）</p>
          </article>
        </section>

        <footer class="detail-footer">
          <RouterLink class="btn primary" :to="`/partition_merge?scope=${encodeURIComponent(detail.scope_id)}`">查看核对视图</RouterLink>
        </footer>
      </section>
    </div>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import {
  getSnapshotPublication,
  listSnapshotPublications,
  type JsonRecord,
} from '@/api/reconciliation'

const route = useRoute()
const router = useRouter()
const publications = ref<JsonRecord[]>([])
const detail = ref<JsonRecord | null>(null)
const loading = ref(false)
const errorMessage = ref('')

async function load(preferredDetail = '') {
  loading.value = true
  errorMessage.value = ''
  try {
    const payload = await listSnapshotPublications()
    publications.value = payload.items
    const detailId = preferredDetail || String(route.query.publication || '')
    if (detailId) await openDetail(detailId, false)
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '快照发布清单读取失败'
  } finally {
    loading.value = false
  }
}

async function openDetail(publicationId: string, updateRoute = true) {
  try {
    const result = await getSnapshotPublication(publicationId)
    if (result.ok === false) throw new Error(result.message)
    detail.value = result
    if (updateRoute) {
      await router.replace({ query: { ...route.query, publication: publicationId } })
    }
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '快照详情读取失败'
  }
}

function closeDetail() {
  detail.value = null
  const query = { ...route.query }
  delete query.publication
  void router.replace({ query })
}

watch(() => route.query.publication, (value) => {
  if (value) void openDetail(String(value), false)
  else detail.value = null
})

onMounted(() => load())
</script>

<style scoped>
.pub-panel { margin: 18px 0; padding: 16px; background: #f8fafc; border: 1px solid var(--border); border-radius: 12px; }
.pub-head { display: flex; justify-content: space-between; gap: 16px; align-items: flex-start; }
.pub-head h3 { margin: 0 0 4px; font-size: 18px; }
.pub-head p { margin: 0; color: var(--muted); font-size: 13px; }
.empty-pub { background: #fff; border: 1px dashed var(--border); padding: 18px; text-align: center; color: var(--muted); border-radius: 8px; }
.pub-list { display: grid; gap: 12px; margin-top: 14px; }
.pub-card { background: #fff; border: 1px solid var(--border); border-radius: 10px; padding: 14px; }
.pub-card header { display: flex; justify-content: space-between; gap: 12px; align-items: flex-start; }
.pub-card h4 { margin: 0 0 4px; }
.pub-card header p { margin: 0; color: var(--muted); font-size: 13px; }
.release-version { background: #dbeafe; color: #1d4ed8; border-radius: 999px; padding: 4px 10px; font-size: 12px; font-weight: 700; white-space: nowrap; }
.pub-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; margin: 12px 0; }
.pub-grid div { background: #f8fafc; border-radius: 8px; padding: 9px; display: grid; gap: 4px; }
.pub-grid span, .detail-grid span { color: var(--muted); font-size: 12px; }
.pub-grid strong { font-size: 14px; }
.scope-description { font-size: 13px; color: #475569; margin: 8px 0; }
.pub-actions { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.pending-pill { background: #fef3c7; color: #92400e; border-radius: 999px; padding: 5px 10px; font-size: 12px; font-weight: 700; }
.detail-backdrop { position: fixed; inset: 0; z-index: 30; background: rgb(15 23 42 / 42%); display: grid; place-items: center; padding: 20px; }
.detail-modal { width: min(980px, 100%); max-height: 90vh; overflow: auto; background: #fff; border-radius: 12px; padding: 18px; box-shadow: 0 24px 60px rgb(15 23 42 / 28%); }
.detail-modal > header { display: flex; justify-content: space-between; gap: 12px; align-items: flex-start; }
.detail-modal h3 { margin: 0 0 4px; }
.detail-modal header p { margin: 0; color: var(--muted); font-size: 13px; }
.detail-section { margin-top: 16px; }
.detail-section h4 { margin: 0 0 8px; font-size: 15px; }
.detail-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; margin-top: 14px; }
.detail-grid div { border: 1px solid var(--border); border-radius: 8px; padding: 9px; display: grid; gap: 4px; }
.conclusion-row { display: flex; gap: 18px; flex-wrap: wrap; background: #f8fafc; padding: 10px; border-radius: 8px; }
.evidence { border-top: 1px solid var(--border); padding: 9px 0; font-size: 13px; }
.evidence header { display: flex; justify-content: space-between; }
.evidence p { margin: 4px 0; color: #475569; }
.detail-footer { margin-top: 18px; display: flex; justify-content: flex-end; }
.muted { color: var(--muted); font-size: 13px; }
.error-text { color: #b42318; }
@media (max-width: 900px) {
  .pub-grid, .detail-grid { grid-template-columns: 1fr 1fr; }
}
</style>
