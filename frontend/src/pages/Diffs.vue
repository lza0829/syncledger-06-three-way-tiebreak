<script setup>
import { onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { getJSON } from '../api'

const route = useRoute()
const rows = ref([])
const err = ref('')
const kindClass = { left_only: 'warn', right_only: 'warn', field_mismatch: 'danger' }
const kindLabel = { left_only: '仅左有', right_only: '仅右有', field_mismatch: '字段不一致' }
const refLabel = {
  adjudicated: '参照裁决',
  awaiting_reference: '待参照',
  reference_divergence: '参照分歧',
  no_reference: '未挂参照',
  not_applicable: '非冲突',
}
const refClass = {
  adjudicated: 'ok',
  awaiting_reference: 'warn',
  reference_divergence: 'danger',
  no_reference: 'warn',
  not_applicable: '',
}

function refSummary (d) {
  const dec = d.decision
  if (!dec) return '—'
  if (dec.overwrite_applied) {
    const side = dec.overwrite_side === 'right' ? '右端' : '左端'
    return `${side}已盖写：${dec.fields.filter(f => f.overwrite).map(f => `${f.field} ${JSON.stringify(f.before)}→${JSON.stringify(f.after)}`).join('; ')}`
  }
  if (d.reference_status === 'reference_divergence') {
    return `参照与左右皆不同（${dec.divergent_fields.join(', ')}），未盖写`
  }
  if (d.reference_status === 'awaiting_reference') {
    return dec.missing_reference ? '参照缺该对齐键，未裁决' : `参照缺字段 ${dec.missing_fields.join(', ')}，未裁决`
  }
  return dec.policy === 'reference_wins' ? '以参照为准：目标侧已等于参照，无变化' : '仅标注，未盖写'
}

async function refresh () {
  const q = route.query.batch_id ? `?batch_id=${route.query.batch_id}` : ''
  rows.value = await getJSON(`/api/diffs${q}`)
}

onMounted(async () => {
  try { await refresh() } catch (e) { err.value = String(e.message || e) }
})
watch(() => route.query.batch_id, async () => {
  try { await refresh() } catch (e) { err.value = String(e.message || e) }
})
</script>
<template>
  <div class="page">
    <h1>差异清单</h1>
    <p class="muted">
      对齐后的差异行。参照状态由「参照裁决」页配置的第三参照夹具产生；待参照/参照分歧一律未裁决、未盖写。
      主从盖写、忽略规则、严重级别闸留给后题。
      <span v-if="route.query.batch_id">当前过滤批次 #{{ route.query.batch_id }}</span>
    </p>
    <p v-if="err" class="tag danger">{{ err }}</p>
    <div class="panel">
      <table>
        <thead>
          <tr>
            <th>ID</th><th>批次</th><th>类型</th><th>对齐键</th><th>不一致字段</th>
            <th>参照状态</th><th>左</th><th>右</th><th>参照</th><th>裁决 / 盖写</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="d in rows" :key="d.id">
            <td>{{ d.id }}</td>
            <td>{{ d.batch_id }}</td>
            <td><span class="tag" :class="kindClass[d.kind]">{{ kindLabel[d.kind] || d.kind }}</span></td>
            <td class="mono">{{ JSON.stringify(d.align_key) }}</td>
            <td class="mono">{{ (d.mismatched_fields || []).join(', ') || '—' }}</td>
            <td><span class="tag" :class="refClass[d.reference_status]">{{ refLabel[d.reference_status] || d.reference_status }}</span></td>
            <td class="mono">{{ d.left ? JSON.stringify(d.left) : '—' }}</td>
            <td class="mono">{{ d.right ? JSON.stringify(d.right) : '—' }}</td>
            <td class="mono">{{ d.reference ? JSON.stringify(d.reference) : '—' }}</td>
            <td class="mono">{{ refSummary(d) }}</td>
          </tr>
          <tr v-if="!rows.length"><td colspan="10" class="muted">暂无差异。去对账台跑一趟后回到这里。</td></tr>
        </tbody>
      </table>
    </div>
  </div>
</template>
