<script setup lang="ts">
import { ref, watch, nextTick, onBeforeUnmount } from "vue";
const props = withDefaults(
  defineProps<{
    open: boolean;
    title: string;
    tabs?: string[];
    active?: string;
    note?: string;
    transactional?: boolean;
    compact?:boolean;
  }>(),
  { tabs: () => [], note: "" },
);
const emit = defineEmits<{
  "update:open": [boolean];
  "update:active": [string];
  apply: [];
}>();
const panel = ref<HTMLElement>();
let previous: HTMLElement | null = null;
function keydown(e: KeyboardEvent) {
  if (!props.open) return;
  if (e.key === "Escape") {
    e.preventDefault();
    emit("update:open", false);
  }
  if (e.key === "Tab" && panel.value) {
    const controls = Array.from(
      panel.value.querySelectorAll<HTMLElement>(
        'button:not(:disabled),input:not(:disabled),select:not(:disabled),textarea:not(:disabled),a[href],[tabindex="0"]',
      ),
    ).filter((e) => e.getClientRects().length);
    const first = controls[0],
      last = controls[controls.length - 1];
    if (e.shiftKey && document.activeElement === first) {
      e.preventDefault();
      last?.focus();
    } else if (!e.shiftKey && document.activeElement === last) {
      e.preventDefault();
      first?.focus();
    }
  }
}
watch(
  () => props.open,
  async (open) => {
    if (open) {
      previous = document.activeElement as HTMLElement;
      await nextTick();
      panel.value?.focus();
      document.addEventListener("keydown", keydown);
    } else {
      document.removeEventListener("keydown", keydown);
      if (previous?.isConnected) previous.focus();
    }
  },
  { immediate: true },
);
onBeforeUnmount(() => document.removeEventListener("keydown", keydown));
</script>
<template>
  <Teleport to="body"
    ><div v-show="open" class="parameter-dialog-backdrop">
      <div
        ref="panel"
        class="parameter-dialog" :class="{'compact-parameter-dialog':compact}"
        role="dialog"
        aria-modal="true"
        :aria-label="title"
        tabindex="-1"
      >
        <div class="parameter-dialog-heading">
          <div>
            <strong>{{ title }}</strong>
            <p>
              {{
                note ||
                (transactional
                  ? "取消或关闭放弃本次修改；应用只接受参数，不提交任务。"
                  : "此模块的保存与计算需通过明确操作执行。")
              }}
            </p>
          </div>
          <button
            @click="emit('update:open', false)"
            :aria-label="'关闭' + title"
          >
            关闭
          </button>
        </div>
        <div
          v-if="tabs.length"
          class="parameter-dialog-tabs"
          role="tablist"
          :aria-label="title + '分类'"
        >
          <button
            v-for="tab in tabs"
            :key="tab"
            role="tab"
            :aria-selected="active === tab"
            :class="{ active: active === tab }"
            @click="emit('update:active', tab)"
          >
            {{ tab }}
          </button>
        </div>
        <div class="parameter-dialog-body"><slot /></div>
        <div class="parameter-dialog-footer">
          <slot name="footer"
            ><template v-if="transactional"
              ><button @click="emit('update:open', false)">取消</button
              ><button class="primary" @click="emit('apply')">
                应用参数
              </button></template
            ><button v-else @click="emit('update:open', false)">
              关闭
            </button></slot
          >
        </div>
      </div>
    </div></Teleport
  >
</template>
<style>
.parameter-dialog-backdrop {
  position: fixed;
  inset: 0;
  background: #17294355;
  min-height: 0;
  z-index: 120;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
}
.parameter-dialog {
  width: min(1140px, calc(100vw - 48px));
  height: min(780px, calc(100vh - 48px));
  display: flex;
  flex-direction: column;
  background: #f4f6fa;
  border: 1px solid #e4e9f0;
  border-radius: 8px;
  box-shadow: 0 12px 40px #17294326;
  overflow: hidden;
  outline: none;
  min-width: 0;
}
.parameter-dialog-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 16px 20px;
  background: #fff;
  border-bottom: 1px solid #e4e9f0;
}
.parameter-dialog-heading strong {
  font-size: 17px;
  color: #172943;
}
.parameter-dialog-heading p {
  margin: 5px 0 0;
  font-size: 12px;
  color: #71819a;
}
.parameter-dialog-tabs {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  padding: 10px 18px;
  background: #fff;
  border-bottom: 1px solid #e4e9f0;
}
.parameter-dialog-tabs button {
  width: auto;
  padding: 8px 12px;
  margin: 0;
}
.parameter-dialog-tabs button.active {
  background: #245fd6;
  color: #fff;
  border-color: #245fd6;
}
.parameter-dialog-body {
  flex: 1;
  min-height: 0;
  overflow: auto;
  overscroll-behavior: contain;
  padding: 16px 18px;
}
.parameter-dialog-body > article {
  margin: 0 0 12px;
}
.parameter-dialog-body section {
  min-height: 0;
  padding: 0;
}
.parameter-dialog-body .parameter-dock {
  position: static;
  width: auto;
  box-shadow: none;
  border: 1px solid #e4e9f0;
}
.parameter-dialog-body .scroll {
  max-width: 100%;
  overflow: auto;
}
.parameter-dialog-body .grid {
  grid-template-columns: repeat(2, minmax(0, 1fr));
}
.parameter-dialog-body label.field {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 8px 0;
}
.parameter-dialog-body input,
.parameter-dialog-body select {
  max-width: 100%;
}
.parameter-dialog-body article {
  min-width: 0;
}
.parameter-dialog-footer {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  padding: 10px 18px;
  background: #fff;
  border-top: 1px solid #e4e9f0;
}
.parameter-dialog-footer button {
  width: auto;
  flex: 0 0 auto;
  margin: 0;
  white-space: nowrap;
  padding: 8px 14px;
}
.parameter-dialog-body .field {
  margin: 4px 0;
  min-height: 42px;
}
.parameter-dialog-body .field input,
.parameter-dialog-body .field select {
  width: 240px;
  flex: 0 0 240px;
}
.parameter-dialog-body .primary {
  width: auto;
  margin: 12px 0;
}
.parameter-dialog-body h3 {
  margin-bottom: 12px;
}
@media (max-width: 800px) {
  .parameter-dialog-backdrop {
    padding: 10px;
  }
  .parameter-dialog {
    width: calc(100vw - 20px);
    height: calc(100vh - 20px);
  }
  .parameter-dialog-body .grid {
    grid-template-columns: 1fr;
  }
}
</style>

<style>.parameter-dialog.compact-parameter-dialog{width:min(810px,calc(100vw - 32px));height:auto;max-height:calc(100dvh - 48px)}.compact-parameter-dialog .parameter-dialog-body{max-height:calc(100dvh - 220px)}.compact-parameter-dialog .parameter-dialog-body .field input{width:110px;flex:0 0 110px}.compact-parameter-dialog .parameter-dialog-body .balance-parameter-grid label.field{display:grid;grid-template-columns:minmax(0,1fr) 110px;gap:8px}.compact-parameter-dialog .parameter-dialog-body .field{min-height:36px;margin:2px 0;padding:5px 0}</style>
