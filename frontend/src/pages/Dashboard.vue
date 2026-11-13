<script setup>
import { onMounted, ref } from 'vue'
import { getJSON } from '../api'
const stats = ref(null)
const err = ref('')
onMounted(async () => {
  try { stats.value = await getJSON('/api/dashboard') } catch (e) { err.value = String(e.message || e) }
})
</script>
<template>
  <div class="page">
    <h1>总览</h1>
    <p class="muted">跨库对齐对账：双端抽取、对齐键匹配、差异记账（默认不自动盖写）。</p>
    <p v-if="err" class="tag danger">{{ err }}</p>
    <div class="panel" v-if="stats">
      <div class="stat-grid">
        <div class="stat"><div class="stat-num">{{ stats.pair_count }}</div><div class="stat-label">对账对</div></div>
        <div class="stat"><div class="stat-num">{{ stats.enabled_pairs }}</div><div class="stat-label">已启用</div></div>
        <div class="stat"><div class="stat-num">{{ stats.batch_count }}</div><div class="stat-label">对账批次</div></div>
        <div class="stat"><div class="stat-num">{{ stats.diff_count }}</div><div class="stat-label">差异行</div></div>
        <div class="stat"><div class="stat-num">{{ stats.open_dispositions }}</div><div class="stat-label">未关处置单</div></div>
      </div>
      <p style="margin-top:1rem">默认策略 <span class="tag">{{ stats.policy }}</span>（只记差异，不盖写两端）</p>
      <p class="muted">第三参照裁决按对账对单独配置：左右一致不读参照；参照缺键与参照分歧都不会被静默冒充成裁决结果。</p>
      <p><router-link to="/run">去对账台跑一趟 →</router-link> · <router-link to="/reference">去看参照裁决 →</router-link></p>
    </div>
  </div>
</template>
