<script setup>
import { computed, onMounted, ref } from 'vue'
import { getJSON, postJSON, putJSON } from '../api'

const pairs = ref([])
const fixtures = ref([])
const batches = ref([])
const pairId = ref(null)
const batchId = ref(null)
const summary = ref(null)
const filter = ref('all')
const err = ref('')
const msg = ref('')
const busy = ref(false)

const form = ref({
  reference_fixture: '',
  reference_policy: 'annotate_only',
  reference_target_side: 'right',
})

const POLICY_LABELS = {
  reference_wins: '以参照为准盖向指定侧',
  annotate_only: '参照只标注、仍不盖写',
}
const BUCKET_LABELS = {
  adjudicated: '参照裁决',
  awaiting_reference: '待参照',
  reference_divergence: '参照分歧',
  no_reference: '未挂参照',
  not_applicable: '非冲突（仅单侧有行）',
}
const BUCKET_ORDER = Object.keys(BUCKET_LABELS)
const KIND_LABELS = { left_only: '仅左有', right_only: '仅右有', field_mismatch: '字段不一致' }

const selectedPair = computed(() => pairs.value.find(p => p.id === pairId.value) || null)
const hasReference = computed(() => Boolean(form.value.reference_fixture))
const visibleDiffs = computed(() => {
  if (!summary.value) return []
  if (filter.value === 'all') return summary.value.diffs
  return summary.value.diffs.filter(d => d.reference_status === filter.value)
})

function statusLabel (s) { return BUCKET_LABELS[s] || s }
function statusClass (s) {
  if (s === 'adjudicated') return 'ok'
  if (s === 'reference_divergence') return 'danger'
  if (s === 'awaiting_reference' || s === 'no_reference') return 'warn'
  return ''
}
function fmt (v) {
  if (v === undefined || v === null) return '—'
  return typeof v === 'object' ? JSON.stringify(v) : String(v)
}
function overwriteText (d) {
  const dec = d.decision
  if (!dec || !dec.overwrite_applied) return '未盖写'
  return `${dec.overwrite_side === 'right' ? '右端' : '左端'}已盖写`
}

function syncForm () {
  const pair = selectedPair.value
  if (!pair) return
  form.value = {
    reference_fixture: pair.reference_fixture || '',
    reference_policy: pair.reference_policy || 'annotate_only',
    reference_target_side: pair.reference_target_side || 'right',
  }
}

async function refresh () {
  pairs.value = await getJSON('/api/pairs')
  fixtures.value = await getJSON('/api/reference/fixtures')
  batches.value = await getJSON('/api/batches?limit=30')
  if (pairId.value == null && pairs.value.length) {
    const demo = pairs.value.find(p => p.reference_fixture) || pairs.value[0]
    pairId.value = demo.id
  }
  if (!batchId.value) selectLatestBatchForPair()
}

function selectLatestBatchForPair () {
  const latest = batches.value.find(b => b.pair_id === pairId.value)
  batchId.value = latest ? latest.id : null
  summary.value = null
}

async function onPairChange () {
  syncForm()
  filter.value = 'all'
  selectLatestBatchForPair()
  await loadSummary()
}

async function saveConfig () {
  err.value = ''
  msg.value = ''
  try {
    const updated = await putJSON(`/api/pairs/${pairId.value}/reference`, {
      reference_fixture: form.value.reference_fixture || null,
      reference_policy: form.value.reference_policy,
      reference_target_side: form.value.reference_target_side,
    })
    pairs.value = pairs.value.map(p => (p.id === updated.id ? updated : p))
    msg.value = hasReference.value
      ? `已保存：参照 ${updated.reference_fixture} · ${POLICY_LABELS[updated.reference_policy]}`
      : '已卸下参照夹具：左右冲突只记差异，不裁决、不盖写'
  } catch (e) {
    err.value = String(e.message || e)
  }
}

async function runOne () {
  err.value = ''
  msg.value = ''
  busy.value = true
  try {
    const batch = await postJSON('/api/reconcile', {
      pair_id: Number(pairId.value),
      note: '参照裁决演示',
    })
    await refresh()
    batchId.value = batch.id
    filter.value = 'all'
    await loadSummary()
  } catch (e) {
    err.value = String(e.message || e)
  } finally {
    busy.value = false
  }
}

async function loadSummary () {
  summary.value = null
  if (!batchId.value) return
  summary.value = await getJSON(`/api/batches/${batchId.value}/reference-summary`)
}

async function onBatchChange () {
  filter.value = 'all'
  try {
    await loadSummary()
  } catch (e) {
    err.value = String(e.message || e)
  }
}

onMounted(async () => {
  try {
    await refresh()
    syncForm()
    await loadSummary()
  } catch (e) {
    err.value = String(e.message || e)
  }
})
</script>

<template>
  <div class="page">
    <h1>参照裁决</h1>
    <p class="muted">
      给对账对挂一份<strong>本地第三参照夹具</strong>，只对「左右字段冲突」做裁决。
      左右一致时不读参照；参照缺键进「待参照」，参照与左右皆不同进「参照分歧」——这两种一律不盖写、不冒充裁决。
      本地夹具不回写，盖写只记在本批次裁决记录里。
    </p>
    <p v-if="err" class="tag danger">{{ err }}</p>
    <p v-if="msg" class="tag ok">{{ msg }}</p>

    <div class="panel">
      <h3 style="margin-top:0">1 · 配置参照</h3>
      <div style="display:flex;flex-wrap:wrap;gap:0.9rem;align-items:flex-end">
        <label>
          对账对
          <select v-model.number="pairId" style="display:block;min-width:22rem;margin-top:0.25rem" @change="onPairChange">
            <option v-for="p in pairs" :key="p.id" :value="p.id">{{ p.title }}</option>
          </select>
        </label>
        <label>
          参照夹具
          <select v-model="form.reference_fixture" style="display:block;min-width:20rem;margin-top:0.25rem">
            <option value="">（不挂参照）</option>
            <option v-for="f in fixtures" :key="f.name" :value="f.name">
              {{ f.name }}{{ f.row_count != null ? ` · ${f.row_count} 行` : '' }}
            </option>
          </select>
        </label>
        <label>
          冲突策略（互斥二选一）
          <select v-model="form.reference_policy" style="display:block;min-width:19rem;margin-top:0.25rem">
            <option value="annotate_only">参照只标注、仍不盖写</option>
            <option value="reference_wins">以参照为准盖向指定侧</option>
          </select>
        </label>
        <label>
          盖写侧
          <select
            v-model="form.reference_target_side"
            :disabled="form.reference_policy !== 'reference_wins'"
            style="display:block;min-width:9rem;margin-top:0.25rem"
          >
            <option value="right">右端</option>
            <option value="left">左端</option>
          </select>
        </label>
        <button @click="saveConfig">保存配置</button>
        <button :disabled="busy || !pairId" class="secondary" @click="runOne">
          {{ busy ? '对账中…' : '2 · 用此配置跑一趟' }}
        </button>
      </div>
      <p class="muted" style="margin-bottom:0">
        当前 <span class="mono">{{ selectedPair?.left_name }} ↔ {{ selectedPair?.right_name }}</span>
        · 对齐键 <span class="mono">{{ (selectedPair?.align_keys || []).join(' + ') }}</span>
        · 比对字段 <span class="mono">{{ (selectedPair?.compare_fields || []).join(', ') }}</span>
      </p>
      <p class="muted" style="margin-bottom:0" v-if="hasReference">
        策略 <span class="tag">{{ POLICY_LABELS[form.reference_policy] }}</span>
        <template v-if="form.reference_policy === 'reference_wins'">
          ，落点 <span class="tag">{{ form.reference_target_side === 'right' ? '右端' : '左端' }}</span>
        </template>
      </p>
      <p class="muted" style="margin-bottom:0" v-else>
        未挂参照：左右冲突仍会记差异，但<strong>不会</strong>得到裁决结论，也不会盖写任何一侧。
      </p>
    </div>

    <div class="panel">
      <h3 style="margin-top:0">2 · 批次互证</h3>
      <label>
        批次
        <select v-model.number="batchId" style="display:block;margin-top:0.35rem;min-width:28rem" @change="onBatchChange">
          <option v-for="b in batches" :key="b.id" :value="b.id">
            {{ b.batch_no }} · #{{ b.id }} · {{ b.pair_title }}
          </option>
        </select>
      </label>

      <template v-if="summary">
        <p style="margin-top:0.85rem">
          <span class="mono">{{ summary.batch.batch_no }}</span> · {{ summary.pair?.title }}
          <span v-if="summary.batch.reference_configured" class="tag" style="margin-left:0.4rem">
            参照 {{ summary.batch.reference_fixture }} · {{ POLICY_LABELS[summary.batch.reference_policy] || summary.batch.reference_policy }}
            <template v-if="summary.batch.reference_policy === 'reference_wins'">
              （盖向{{ summary.batch.reference_target_side === 'right' ? '右端' : '左端' }}）
            </template>
          </span>
          <span v-else class="tag warn" style="margin-left:0.4rem">未挂参照</span>
        </p>

        <div class="stat-grid">
          <div class="stat">
            <div class="stat-num">{{ summary.counts.reference_hit }}</div>
            <div class="stat-label">
              参照命中 · {{ summary.batch.reference_policy === 'reference_wins' ? '盖写' : '仅标注' }}
            </div>
          </div>
          <div class="stat">
            <div class="stat-num">{{ summary.counts.reference_awaiting }}</div>
            <div class="stat-label">待参照（未裁决）</div>
          </div>
          <div class="stat">
            <div class="stat-num">{{ summary.counts.reference_divergent }}</div>
            <div class="stat-label">参照分歧（未盖写）</div>
          </div>
          <div class="stat">
            <div class="stat-num">{{ summary.counts.diff_total }}</div>
            <div class="stat-label">差异合计</div>
          </div>
          <div class="stat">
            <div class="stat-num">{{ summary.counts.overwrite_applied }}</div>
            <div class="stat-label">实际盖写行</div>
          </div>
        </div>

        <p style="margin-top:0.75rem">
          计数与差异列表
          <span class="tag" :class="summary.consistent ? 'ok' : 'danger'">
            {{ summary.consistent ? '一致' : '不一致' }}
          </span>
          <span class="muted mono" style="margin-left:0.5rem">
            命中 {{ summary.stored.reference_hit }} / 待参照 {{ summary.stored.reference_awaiting }} / 分歧 {{ summary.stored.reference_divergent }}
          </span>
        </p>
        <p v-if="!summary.consistent" class="tag danger">
          <span v-for="c in summary.checks.filter(x => !x.ok)" :key="c.key">
            {{ c.key }} 存储 {{ c.stored }} ≠ 列表重算 {{ c.recomputed }}；
          </span>
        </p>

        <div style="margin-top:0.85rem;display:flex;flex-wrap:wrap;gap:0.4rem">
          <button class="secondary" :class="{ 'active-filter': filter === 'all' }" @click="filter = 'all'">
            全部差异 ({{ summary.diffs.length }})
          </button>
          <button
            v-for="b in BUCKET_ORDER"
            :key="b"
            class="secondary"
            :class="{ 'active-filter': filter === b }"
            @click="filter = b"
          >
            {{ BUCKET_LABELS[b] }} ({{ (summary.buckets[b] || []).length }})
          </button>
        </div>

        <table style="margin-top:0.75rem">
          <thead>
            <tr>
              <th>对齐键</th><th>类型</th><th>参照状态</th><th>左值</th><th>右值</th>
              <th>参照值</th><th>裁决 / 盖写</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="d in visibleDiffs" :key="d.id">
              <td class="mono">{{ JSON.stringify(d.align_key) }}</td>
              <td>{{ KIND_LABELS[d.kind] || d.kind }}</td>
              <td>
                <span class="tag" :class="statusClass(d.reference_status)">{{ statusLabel(d.reference_status) }}</span>
              </td>
              <td class="mono">{{ d.left ? JSON.stringify(d.left) : '—' }}</td>
              <td class="mono">{{ d.right ? JSON.stringify(d.right) : '—' }}</td>
              <td class="mono">{{ d.reference ? JSON.stringify(d.reference) : '—' }}</td>
              <td>
                <div v-if="d.decision">
                  <span class="tag" :class="d.decision.overwrite_applied ? 'ok' : 'warn'">{{ overwriteText(d) }}</span>
                  <div
                    v-for="f in d.decision.fields"
                    :key="f.field"
                    class="mono"
                    style="font-size:0.82rem;margin-top:0.2rem"
                  >
                    {{ f.field }}：参照={{ fmt(f.reference) }}
                    <template v-if="f.ref_matches">（= {{ f.ref_matches === 'left' ? '左' : '右' }}）</template>
                    <template v-else>（与左右皆不同）</template>
                    <template v-if="f.overwrite">· {{ f.overwrite === 'right' ? '右' : '左' }}端 {{ fmt(f.before) }} → {{ fmt(f.after) }}</template>
                  </div>
                  <div v-if="d.reference_status === 'reference_divergence'" class="mono" style="font-size:0.82rem;color:var(--danger)">
                    参照与左右皆不同：按策略不盖写，也不以任一侧冒充裁决
                  </div>
                  <div v-else-if="d.reference_status === 'awaiting_reference'" class="mono" style="font-size:0.82rem;color:var(--warn)">
                    参照缺{{ d.decision.missing_reference ? '该对齐键' : '字段 ' + (d.decision.missing_fields || []).join(', ') }}：待参照，未裁决
                  </div>
                </div>
                <span v-else class="muted">—</span>
              </td>
            </tr>
            <tr v-if="!visibleDiffs.length">
              <td colspan="7" class="muted">该分桶为空。</td>
            </tr>
          </tbody>
        </table>
      </template>
      <p v-else class="muted">还没有批次。先跑一趟。</p>
    </div>
  </div>
</template>
