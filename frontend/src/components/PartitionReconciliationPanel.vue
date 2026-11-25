<template>
  <section class="recon-panel" data-testid="partition-rewrite-reconciliation">
    <div class="recon-head">
      <div>
        <h3>分区重写核对视图</h3>
        <p>按源分区、目标分区计算实际移出、实际移入和待核差异；登记快照时同步到快照发布清单。</p>
      </div>
      <div class="recon-head-actions">
        <button class="btn" type="button" data-testid="new-recon-scope" @click="createSession">新建核对范围</button>
        <button class="btn ghost" type="button" data-testid="reset-recon-demo" @click="resetDemo">重置 M41 场景</button>
      </div>
    </div>

    <form class="recon-filter" data-testid="recon-partition-filter" @submit.prevent="applyPartitionFilter">
      <label>
        <span>源分区</span>
        <input v-model="sourceFilter" data-testid="filter-source-partition" placeholder="例如 p3" />
      </label>
      <label>
        <span>目标分区</span>
        <input v-model="targetFilter" data-testid="filter-target-partition" placeholder="例如 p4" />
      </label>
      <button class="btn primary" type="submit" data-testid="query-reconciliation-by-partition">按源/目标查询</button>
      <button class="btn ghost" type="button" data-testid="reset-recon-filter" @click="resetPartitionFilter">显示全部</button>
    </form>

    <div class="recon-view-tabs" data-testid="recon-view-list">
      <button
        v-for="item in views"
        :key="item.id"
        type="button"
        class="recon-view-tab"
        :class="{ active: view?.id === item.id }"
        :data-testid="`recon-view-${item.task_code}`"
        @click="chooseScope(item.id)"
      >
        <strong>{{ item.task_code }}</strong>
        <span>{{ item.source_partition }} → {{ item.target_partition }}</span>
        <em :data-published="Boolean(item.publication_id)">{{ item.publication_id ? '已发布' : item.status }}</em>
      </button>
    </div>

    <p v-if="errorMessage" class="error-text" role="alert" data-testid="recon-error">{{ errorMessage }}</p>
    <p v-if="actionMessage" class="ok-text" role="status" data-testid="recon-message">{{ actionMessage }}</p>

    <div v-if="loading && !view" class="recon-loading">正在读取分区重写核对视图…</div>

    <article v-if="view" class="recon-detail" :data-scope-id="view.id" data-testid="reconciliation-view">
      <header class="recon-detail-head">
        <div>
          <h4>{{ view.title }}</h4>
          <p class="scope-statement" data-testid="scope-statement">{{ view.scope_statement }}</p>
          <p v-if="view.scope_adoption_statement" class="adoption-statement" data-testid="adoption-statement">
            本次采用范围：{{ view.scope_adoption_statement }}
          </p>
        </div>
        <div class="recon-actions" data-testid="recon-actions">
          <label class="late-value-field">
            <span>k5 更正值（可选）</span>
            <input v-model="lateValue" data-testid="late-k5-value" placeholder="默认：1005@late-corrected-v2" />
          </label>
          <button class="btn" type="button" data-testid="late-correct-k5" :disabled="busy" @click="lateCorrectK5">
            旧 p3 迟到更新 k5
          </button>
          <button class="btn" type="button" data-testid="reverify-current" :disabled="busy" @click="reverify">
            登记前重新核验当前来源
          </button>
          <fieldset class="publish-mode" data-testid="publish-mode">
            <legend>快照发布范围</legend>
            <label>
              <input v-model="publishMode" type="radio" value="opened" data-testid="publish-mode-opened" />
              <span>沿用原范围：沿用打开视图时的已核范围（RV-M41-v1）</span>
            </label>
            <label>
              <input v-model="publishMode" type="radio" value="refreshed" data-testid="publish-mode-refreshed" />
              <span>刷新后版本：登记前重新核验当前来源，并采用更正后的核对版本（RV-M41-v2）</span>
            </label>
          </fieldset>
          <div class="publish-shortcuts">
            <button
              class="btn"
              type="button"
              data-testid="publish-opened-scope"
              :disabled="busy || Boolean(view.publication_id)"
              @click="publish('opened')"
            >
              沿用原范围并登记
            </button>
            <button
              class="btn"
              type="button"
              data-testid="publish-refreshed-version"
              :disabled="busy || Boolean(view.publication_id)"
              @click="publish('refreshed')"
            >
              刷新后版本并登记
            </button>
          </div>
          <button
            class="btn primary register-btn"
            type="button"
            data-testid="register-snapshot"
            :disabled="busy || Boolean(view.publication_id)"
            @click="publish(publishMode)"
          >
            登记快照
          </button>
        </div>
      </header>

      <div class="k5-strip" data-testid="k5-strip">
        <span>p4 的 k5 当前可读值（按本次拟采用版本）：</span>
        <code data-testid="p4-k5">{{ k5ReadableValue }}</code>
        <small>打开时：{{ openedK5Value }}；当前来源：{{ currentK5Value }}</small>
      </div>

      <div class="recon-metric-row" data-testid="recon-metrics">
        <div class="recon-metric" data-testid="metric-moved-out">
          <span>实际移出</span>
          <strong>{{ displaySummary.actual_moved_out_count ?? 0 }}</strong>
          <small>去重移出键 {{ displaySummary.distinct_moved_out_keys ?? 0 }}，重复计数 {{ displaySummary.duplicate_move_count ?? 0 }}</small>
        </div>
        <div class="recon-metric" data-testid="metric-moved-in">
          <span>实际移入</span>
          <strong>{{ displaySummary.actual_moved_in_count ?? 0 }}</strong>
        </div>
        <div class="recon-metric warn" data-testid="metric-pending-diff">
          <span>待核差异</span>
          <strong>{{ displaySummary.pending_difference_count ?? 0 }}</strong>
        </div>
        <div class="recon-metric" data-testid="metric-pending-records">
          <span>仍待处理记录</span>
          <strong>{{ view.pending_record_count ?? pendingRecords.length }}</strong>
        </div>
        <div class="recon-metric" data-testid="metric-source-revision">
          <span>打开时 / 当前来源版本</span>
          <strong>r{{ view.source_revision_at_open }} / r{{ view.source_revision_current }}</strong>
        </div>
      </div>

      <section v-if="publication || view.publication_id" class="publication-banner" data-testid="publication-result">
        <div>
          <h5>快照发布清单已同步</h5>
          <p>
            快照 <strong data-testid="published-snapshot-id">{{ publication?.snapshot_id || view.snapshot_id }}</strong>
            ｜发布版本 <strong data-testid="published-release-version">{{ publication?.release_version || '—' }}</strong>
            ｜核对版本 <strong data-testid="published-recon-version">{{ publication?.published_version || view.adopted_version_id }}</strong>
          </p>
          <p data-testid="published-scope-mode">
            本次采用范围：{{ scopeModeText(publication?.scope_mode || view.publish_mode) }}
          </p>
          <p class="scope-description" data-testid="published-scope-description">
            {{ publication?.published_scope_description || view.scope_adoption_statement }}
          </p>
          <p v-if="publication?.idempotent_replay" class="ok-text">该核对范围已发布；本次重试返回同一份快照，没有重复发布。</p>
        </div>
        <RouterLink
          v-if="publication"
          class="btn primary"
          :to="`/snapshot_mgr?publication=${encodeURIComponent(publication.publication_id)}`"
          data-testid="link-snapshot-detail"
        >
          查看快照详情
        </RouterLink>
      </section>

      <div class="recon-grid">
        <section class="recon-table-card" data-testid="reconciliation-data-table">
          <div class="table-head-row">
            <h5>分区重写核对视图数据</h5>
            <div class="version-switch" data-testid="version-switch">
              <button
                type="button"
                :class="{ active: tableVersion === 'opened' }"
                data-testid="show-opened-version"
                @click="tableVersion = 'opened'"
              >
                打开时已核 v1
              </button>
              <button
                type="button"
                :class="{ active: tableVersion === 'current' }"
                data-testid="show-current-check"
                @click="tableVersion = 'current'"
              >
                当前来源重核
              </button>
              <button
                v-if="view.adopted_version_id"
                type="button"
                :class="{ active: tableVersion === 'adopted' }"
                data-testid="show-adopted-version"
                @click="tableVersion = 'adopted'"
              >
                发布采用 {{ view.adopted_version_id }}
              </button>
            </div>
          </div>
          <p class="table-version-note" data-testid="table-version-note">{{ versionNote }}</p>
          <div class="table-scroll">
            <table class="data-table">
              <thead>
                <tr>
                  <th>Row Key</th>
                  <th>源分区</th>
                  <th>源值/依据</th>
                  <th>目标分区</th>
                  <th>p4 可读值</th>
                  <th>p4 存储值</th>
                  <th>移出/移入</th>
                  <th>核对结论</th>
                </tr>
              </thead>
              <tbody>
                <tr
                  v-for="row in displayRows"
                  :key="row.key"
                  :data-testid="`recon-row-${row.key}`"
                  :data-status="row.status"
                  :class="{ pending: row.pending_difference, adopted: row.correction_adopted }"
                >
                  <td><strong>{{ row.key }}</strong></td>
                  <td>{{ row.source_partition }}</td>
                  <td>
                    <code>{{ row.source_value ?? '—' }}</code>
                    <small v-if="row.source_changed_after_open" class="changed">当前来源：{{ row.current_source_value }}</small>
                  </td>
                  <td>{{ row.target_partition }}</td>
                  <td><code :data-testid="`p4-readable-value-${row.key}`">{{ row.p4_readable_value ?? '—' }}</code></td>
                  <td><code>{{ row.stored_p4_value ?? '—' }}</code></td>
                  <td>{{ row.move_status }}</td>
                  <td>
                    {{ row.status_label }}
                    <small v-if="row.counted_once && row.move_count === 1" class="once">移出仅计一次</small>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </section>

        <aside class="recon-side">
          <section class="evidence-card" data-testid="source-evidence">
            <h5>更正前后来源证据</h5>
            <article v-for="ev in view.source_evidence || []" :key="ev.evidence_id" class="evidence-item" :data-testid="`evidence-${ev.row_key}-r${ev.revision}`">
              <header>
                <strong>{{ ev.evidence_id }}</strong>
                <span>{{ ev.kind === 'late_correction' ? '迟到更正' : '打开基线' }}</span>
              </header>
              <p>{{ ev.partition }} / {{ ev.row_key }} / r{{ ev.revision }}</p>
              <div v-if="ev.before" class="evidence-before">更正前：<code>{{ ev.before.value }}</code></div>
              <div v-if="ev.after" class="evidence-after">更正后：<code>{{ ev.after.value }}</code></div>
            </article>
          </section>

          <section class="pending-card" data-testid="pending-records">
            <div class="card-title-row">
              <h5>仍待处理记录</h5>
              <span class="count-badge" data-testid="pending-record-count">{{ pendingRecords.length }}</span>
            </div>
            <ul>
              <li v-for="record in pendingRecords" :key="record.id" :data-testid="`pending-${record.row_key}`" :data-type="record.type">
                <strong>{{ record.id }}</strong>
                <span>{{ record.status }}</span>
                <p>{{ record.message }}</p>
              </li>
            </ul>
          </section>
        </aside>
      </div>
    </article>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import {
  applyLateCorrection,
  getReconciliationView,
  getSnapshotPublication,
  listReconciliationViews,
  openReconciliationView,
  publishReconciliationSnapshot,
  resetReconciliationDemo,
  reverifyReconciliation,
  type JsonRecord,
} from '@/api/reconciliation'

const emit = defineEmits<{ published: [] }>()
const route = useRoute()
const router = useRouter()

const views = ref<JsonRecord[]>([])
const view = ref<JsonRecord | null>(null)
const publication = ref<JsonRecord | null>(null)
const loading = ref(false)
const busy = ref(false)
const errorMessage = ref('')
const actionMessage = ref('')
const lateValue = ref('')
const sourceFilter = ref('')
const targetFilter = ref('')
const publishMode = ref<'opened' | 'refreshed'>('opened')
const tableVersion = ref<'opened' | 'current' | 'adopted'>('opened')

const adoptedView = computed<JsonRecord | null>(() => {
  if (!view.value) return null
  const adoptedId = view.value.adopted_version_id
  return view.value.versions?.find((item: JsonRecord) => item.version_id === adoptedId) || view.value.opened_view
})

const adoptedSummary = computed<JsonRecord>(() => adoptedView.value?.summary || view.value?.opened_view?.summary || {})
const displayView = computed<JsonRecord | null>(() => {
  if (tableVersion.value === 'current') return view.value?.current_check || view.value?.opened_view || null
  if (tableVersion.value === 'adopted') return adoptedView.value || view.value?.opened_view || null
  return view.value?.opened_view || null
})
const displaySummary = computed<JsonRecord>(() => displayView.value?.summary || adoptedSummary.value)
const displayRows = computed<JsonRecord[]>(() => displayView.value?.rows || [])
const versionNote = computed(() => {
  if (tableVersion.value === 'current') {
    return '当前来源重核预览：迟到更正已标为差异；只有选择“刷新后版本”并登记快照，才会形成 RV-M41-v2 依据。'
  }
  if (tableVersion.value === 'adopted') {
    return `本次发布采用版本：${view.value?.adopted_version_id || ''}。`
  }
  return '打开视图时固化的已核范围；后续迟到更正不会改写这一版证据。'
})
const pendingRecords = computed<JsonRecord[]>(() => view.value?.pending_records || [])
const openedK5Row = computed<JsonRecord | undefined>(
  () => view.value?.opened_view?.rows?.find((row: JsonRecord) => row.key === 'k5'),
)
const currentK5Row = computed<JsonRecord | undefined>(
  () => view.value?.current_check?.rows?.find((row: JsonRecord) => row.key === 'k5'),
)
const openedK5Value = computed(() => openedK5Row.value?.p4_readable_value ?? '—')
const currentK5Value = computed(
  () => currentK5Row.value?.current_source_value ?? currentK5Row.value?.source_value ?? '—',
)
const k5ReadableValue = computed(() => {
  if (publication.value?.p4_k5_readable_value) return publication.value.p4_k5_readable_value
  if (view.value?.adopted_version_id) {
    return adoptedView.value?.rows?.find((row: JsonRecord) => row.key === 'k5')?.p4_readable_value ?? '—'
  }
  return publishMode.value === 'refreshed' ? currentK5Value.value : openedK5Value.value
})

function scopeModeText(mode: string | null | undefined): string {
  if (mode === 'refreshed') return '登记前重新核验当前来源，并采用更正后的核对版本（RV-M41-v2）'
  if (mode === 'opened') return '沿用打开视图时的已核范围（RV-M41-v1）'
  return '尚未发布'
}

function scopeFromQuery(): string {
  return String(route.query.scope || route.query.reconciliation || '')
}

async function loadViews(preferredId = '') {
  loading.value = true
  errorMessage.value = ''
  try {
    const filters = {
      source_partition: sourceFilter.value,
      target_partition: targetFilter.value,
    }
    const payload = await listReconciliationViews(filters)
    views.value = payload.items
    const hasPartitionFilter = Boolean(sourceFilter.value.trim() || targetFilter.value.trim())
    const targetId = preferredId
      || scopeFromQuery()
      || (!hasPartitionFilter ? view.value?.id : '')
      || payload.items[0]?.id
    if (targetId) {
      await selectScope(targetId, false)
    } else {
      view.value = null
      publication.value = null
      actionMessage.value = '没有符合该源、目标分区的重写核对视图。'
    }
    return payload
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '核对视图列表读取失败'
    return { items: [], total: 0 }
  } finally {
    loading.value = false
  }
}

async function selectScope(scopeId: string, clearMessage = true) {
  if (clearMessage) {
    errorMessage.value = ''
    actionMessage.value = ''
  }
  try {
    const detail = await getReconciliationView(scopeId)
    if (detail.ok === false) throw new Error(detail.message)
    view.value = detail
    if (detail.publish_mode === 'refreshed' || detail.publish_mode === 'opened') {
      publishMode.value = detail.publish_mode
    }
    tableVersion.value = detail.adopted_version_id ? 'adopted' : 'opened'
    if (detail.publication_id) {
      try {
        publication.value = await getSnapshotPublication(String(detail.publication_id))
      } catch {
        publication.value = {
          publication_id: detail.publication_id,
          snapshot_id: detail.snapshot_id,
          scope_id: detail.id,
          scope_mode: detail.publish_mode,
          published_version: detail.adopted_version_id,
        }
      }
    } else if (publication.value?.scope_id !== detail.id) {
      publication.value = null
    }
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '核对视图读取失败'
  }
}

async function chooseScope(scopeId: string) {
  await selectScope(scopeId)
  await router.replace({ query: { ...route.query, scope: scopeId } })
}

async function applyPartitionFilter() {
  actionMessage.value = ''
  await loadViews()
}

async function resetPartitionFilter() {
  sourceFilter.value = ''
  targetFilter.value = ''
  actionMessage.value = ''
  await loadViews()
}

async function createSession() {
  busy.value = true
  errorMessage.value = ''
  actionMessage.value = ''
  try {
    const created = await openReconciliationView({ task_code: 'M41', new_session: true })
    if (created.ok === false) throw new Error(created.message)
    await loadViews(created.id)
    await router.replace({ query: { ...route.query, scope: created.id } })
    actionMessage.value = '已打开新的 M41 核对范围；该范围只可发布一次。'
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '新建核对范围失败'
  } finally {
    busy.value = false
  }
}

async function lateCorrectK5() {
  if (!view.value) return
  busy.value = true
  errorMessage.value = ''
  try {
    const result = await applyLateCorrection(view.value.id, {
      key: 'k5',
      value: lateValue.value.trim() || undefined,
      source_partition: 'p3',
    })
    if (result.ok === false) throw new Error(result.message)
    view.value = result
    actionMessage.value = result.message || 'k5 迟到更正已留证'
    await loadViews(result.id)
    tableVersion.value = 'current'
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '迟到更正登记失败'
  } finally {
    busy.value = false
  }
}

async function reverify() {
  if (!view.value) return
  busy.value = true
  errorMessage.value = ''
  try {
    const result = await reverifyReconciliation(view.value.id)
    if (result.ok === false) throw new Error(result.message)
    view.value = result
    tableVersion.value = 'current'
    actionMessage.value = '已生成当前来源重核预览；选择“刷新后版本并登记快照”才会采用 v2。'
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '重新核验失败'
  } finally {
    busy.value = false
  }
}

async function publish(mode: 'opened' | 'refreshed') {
  if (!view.value) return
  busy.value = true
  errorMessage.value = ''
  actionMessage.value = ''
  const idempotencyKey = `idem-${view.value.id}`
  try {
    const result = await publishReconciliationSnapshot(view.value.id, { mode }, idempotencyKey)
    if (result.ok === false) throw new Error(result.message)
    publication.value = result
    actionMessage.value = result.idempotent_replay
      ? '断线重试或并发登记已返回唯一快照，未重复发布。'
      : `快照 ${result.snapshot_id} 已登记，核对结论已同步到发布清单。`
    await selectScope(view.value.id)
    await loadViews(view.value.id)
    emit('published')
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '快照登记失败'
    // 网络断线/响应丢失后恢复视图，后端范围幂等仍可找回已发布快照。
    await selectScope(view.value.id)
    if (view.value?.publication_id) {
      try {
        publication.value = await getSnapshotPublication(String(view.value.publication_id))
        errorMessage.value = ''
        actionMessage.value = '连接恢复后已找回本次唯一快照及发布依据。'
      } catch {
        // 保留视图中的发布编号和证据。
      }
    }
  } finally {
    busy.value = false
  }
}

async function resetDemo() {
  busy.value = true
  try {
    await resetReconciliationDemo()
    publication.value = null
    await loadViews()
    actionMessage.value = 'M41 场景已重置为视图刚打开、k5 尚未迟到更正的状态。'
  } finally {
    busy.value = false
  }
}

watch(() => route.query.scope, (value) => {
  const scopeId = String(value || '')
  if (scopeId && scopeId !== view.value?.id) void selectScope(scopeId)
})

onMounted(() => loadViews())
</script>

<style scoped>
.recon-panel { margin: 18px 0; padding: 16px; background: #f8fafc; border: 1px solid var(--border); border-radius: 12px; }
.recon-head { display: flex; justify-content: space-between; gap: 16px; align-items: flex-start; }
.recon-head h3 { margin: 0 0 4px; font-size: 18px; }
.recon-head p { margin: 0; color: var(--muted); font-size: 13px; }
.recon-head-actions { display: flex; gap: 8px; flex-shrink: 0; }
.recon-filter { display: flex; flex-wrap: wrap; align-items: flex-end; gap: 10px; background: #fff; border: 1px solid var(--border); border-radius: 8px; padding: 10px; margin: 12px 0; }
.recon-filter label { display: grid; gap: 4px; font-size: 12px; color: var(--muted); }
.recon-filter input { border: 1px solid var(--border); border-radius: 6px; padding: 7px 9px; min-width: 160px; }
.recon-view-tabs { display: flex; gap: 8px; margin: 14px 0; flex-wrap: wrap; }
.recon-view-tab { display: grid; gap: 2px; padding: 8px 12px; border: 1px solid var(--border); background: #fff; border-radius: 8px; cursor: pointer; text-align: left; }
.recon-view-tab.active { border-color: var(--brand); box-shadow: 0 0 0 2px rgb(31 111 235 / 12%); }
.recon-view-tab span { font-size: 12px; color: var(--muted); }
.recon-view-tab em { font-style: normal; font-size: 12px; color: #b45309; }
.recon-view-tab em[data-published="true"] { color: #15803d; }
.recon-detail { background: #fff; border: 1px solid var(--border); border-radius: 10px; padding: 14px; }
.recon-detail-head { display: flex; justify-content: space-between; gap: 16px; align-items: flex-start; }
.recon-detail-head h4 { margin: 0 0 6px; font-size: 16px; }
.scope-statement, .adoption-statement { margin: 3px 0; font-size: 13px; color: #334155; }
.adoption-statement { color: #1d4ed8; font-weight: 600; }
.recon-actions { display: flex; flex-wrap: wrap; gap: 8px; justify-content: flex-end; max-width: 520px; }
.late-value-field { display: grid; gap: 3px; font-size: 12px; color: var(--muted); width: 100%; }
.late-value-field input { border: 1px solid var(--border); border-radius: 6px; padding: 7px 9px; }
.publish-mode { width: 100%; border: 1px solid var(--border); border-radius: 8px; padding: 8px 10px; margin: 0; display: grid; gap: 5px; text-align: left; }
.publish-mode legend { font-size: 12px; color: var(--muted); padding: 0 4px; }
.publish-mode label { display: flex; gap: 7px; align-items: flex-start; font-size: 13px; cursor: pointer; }
.publish-shortcuts { display: flex; gap: 8px; flex-wrap: wrap; width: 100%; }
.register-btn { align-self: flex-end; }
.k5-strip { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; border: 1px solid #bfdbfe; background: #eff6ff; border-radius: 8px; padding: 9px 12px; margin-bottom: 12px; font-size: 13px; }
.k5-strip code { font-size: 14px; font-weight: 700; background: #dbeafe; padding: 2px 6px; border-radius: 5px; }
.k5-strip small { color: var(--muted); }
.card-title-row { display: flex; align-items: center; justify-content: space-between; margin-bottom: 10px; }
.card-title-row h5 { margin: 0; }
.count-badge { min-width: 22px; text-align: center; background: #fef3c7; color: #92400e; border-radius: 999px; padding: 2px 7px; font-size: 12px; font-weight: 700; }
.recon-metric-row { display: grid; grid-template-columns: repeat(5, minmax(120px, 1fr)); gap: 10px; margin: 14px 0; }
.recon-metric { background: #f8fafc; border: 1px solid var(--border); border-radius: 8px; padding: 10px; display: grid; gap: 3px; }
.recon-metric span { font-size: 12px; color: var(--muted); }
.recon-metric strong { font-size: 22px; }
.recon-metric small { color: var(--muted); font-size: 11px; line-height: 1.35; }
.recon-metric.warn strong { color: #b45309; }
.publication-banner { display: flex; justify-content: space-between; gap: 14px; align-items: center; border: 1px solid #86efac; background: #f0fdf4; border-radius: 10px; padding: 12px; margin-bottom: 14px; }
.publication-banner h5 { margin: 0 0 6px; color: #15803d; }
.publication-banner p { margin: 3px 0; font-size: 13px; }
.scope-description { color: #475569; }
.recon-grid { display: grid; grid-template-columns: minmax(0, 1.7fr) minmax(300px, .8fr); gap: 14px; }
.recon-table-card, .evidence-card, .pending-card { background: #fff; border: 1px solid var(--border); border-radius: 8px; padding: 12px; }
.recon-table-card h5, .evidence-card h5, .pending-card h5 { margin: 0 0 10px; font-size: 14px; }
.table-head-row { display: flex; justify-content: space-between; gap: 10px; align-items: center; flex-wrap: wrap; margin-bottom: 6px; }
.table-head-row h5 { margin-bottom: 0; }
.version-switch { display: inline-flex; gap: 4px; flex-wrap: wrap; }
.version-switch button { border: 1px solid var(--border); background: #f8fafc; border-radius: 999px; padding: 4px 9px; font-size: 12px; cursor: pointer; }
.version-switch button.active { background: #dbeafe; border-color: #93c5fd; color: #1d4ed8; font-weight: 700; }
.table-version-note { margin: 0 0 10px; color: var(--muted); font-size: 12px; }
.table-scroll { overflow: auto; max-width: 100%; }
.table-scroll .data-table { min-width: 860px; }
.data-table code { font-size: 12px; background: #f1f5f9; padding: 1px 4px; border-radius: 4px; }
.data-table small { display: block; color: var(--muted); margin-top: 3px; }
.data-table small.changed { color: #b45309; }
.data-table small.once { color: #15803d; }
.data-table tr.pending { background: #fffbeb; }
.data-table tr.adopted { background: #eff6ff; }
.recon-side { display: grid; gap: 12px; align-content: start; }
.evidence-item { border-top: 1px solid #e2e8f0; padding: 9px 0; font-size: 12px; }
.evidence-item header { display: flex; justify-content: space-between; gap: 8px; }
.evidence-item header span { color: #b45309; }
.evidence-item p { color: var(--muted); margin: 4px 0; }
.evidence-before, .evidence-after { margin: 3px 0; }
.evidence-after { color: #1d4ed8; }
.pending-card ul { list-style: none; margin: 0; padding: 0; display: grid; gap: 8px; }
.pending-card li { border: 1px solid #fde68a; background: #fffbeb; border-radius: 7px; padding: 8px; display: grid; gap: 3px; font-size: 12px; }
.pending-card li span { color: #92400e; font-weight: 600; }
.pending-card li p { margin: 0; color: #57534e; }
.ok-text { color: #15803d; font-size: 13px; }
.error-text { color: #b42318; font-size: 13px; }
.recon-loading { padding: 18px; color: var(--muted); }
@media (max-width: 1100px) {
  .recon-grid { grid-template-columns: 1fr; }
  .recon-metric-row { grid-template-columns: repeat(2, 1fr); }
  .recon-detail-head { flex-direction: column; }
  .recon-actions { justify-content: flex-start; max-width: none; }
}
</style>
