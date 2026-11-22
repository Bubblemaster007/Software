<script setup lang="ts">
import ParameterDialog from "./ParameterDialog.vue";
defineProps<{ enabled: boolean; open: boolean; title: string }>();
const emit = defineEmits<{ "update:open": [boolean] }>();
</script>
<template>
  <ParameterDialog
    v-if="enabled"
    :open="open"
    :title="title"
    note="台账独立校验保存并保留版本；关闭放弃本次未保存修改。"
    @update:open="emit('update:open', $event)"
    ><slot /><template #footer
      ><slot name="footer" /></template></ParameterDialog
  ><slot v-else />
</template>
