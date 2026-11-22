<script setup lang="ts">
import { computed } from "vue";
import StudyTasks from "./StudyTasks.vue";
import { useEngineeringContext } from "./useEngineeringProject";
const { taskFocus,project, result, busy, progressEvidence } = useEngineeringContext();
const nativeJobs = computed(
  () =>
    progressEvidence.snapshot.value?.jobs?.filter(
      (j: any) => j.module === "native",
    ) || [],
);
const statusNames: Record<string, string> = {
  queued: "排队中",
  running: "计算中",
  succeeded: "计算完成",
  failed: "计算失败",
  interrupted: "已中断",
};
</script>
<template>
  <p v-if="busy" role="status">
    正在处理当前工程请求；同步平衡接口未提供精确进度。
  </p>
  <p v-if="result">
    已选平衡档案 {{ result.id }} · 输入版本
    {{ result.project_revision ?? "未记录" }} · 已归档
  </p>
  <StudyTasks :focus-id="taskFocus" :project-id="project?.id || ''" />
  <details v-if="nativeJobs.length">
    <summary>原生年度任务（{{ nativeJobs.length }}）</summary>
    <table>
      <tr>
        <th>任务</th>
        <th>状态</th>
        <th>输入版本</th>
        <th>创建时间</th>
        <th>冻结档案</th>
      </tr>
      <tr v-for="j in nativeJobs" :key="j.id">
        <td>{{ j.id.slice(0, 8) }}</td>
        <td>{{ statusNames[j.status] || j.status }}</td>
        <td>{{ j.project_revision ?? "未记录" }}</td>
        <td>{{ j.created }}</td>
        <td>
          <a :href="'/api/native-jobs/' + j.id + '/input'" target="_blank"
            >输入快照</a
          >
          <a
            v-if="!['queued', 'running'].includes(j.status)"
            :href="'/api/native-jobs/' + j.id + '/archive'"
            >任务 ZIP</a
          >
        </td>
      </tr>
    </table>
    <p>
      原生队列没有取消接口。完整文件查看及新的任务配置保留在“原生年度流水线”模式。
    </p>
  </details>
</template>
