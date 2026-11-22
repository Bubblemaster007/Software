<script setup lang="ts">
import { onBeforeUnmount } from "vue";
import type { Command } from "./commands";
import { workspaces,stageDisplayNames } from "./workspaceRegistry";
const props = defineProps<{
  project: any;
  projects: any[];
  workspace: string;
  progress: Record<string, any>;
  commands: Command[];
  menus: { label: string; ids: string[] }[];
  disabled: (c: Command) => boolean;
  busy: boolean;
  status: string;
  compact: boolean;
  presentation: boolean;
  bottom: string;
  bottomHeight: number;
  right: string;
  rightWidth: number;
}>();
const emit = defineEmits<{
  command: [id: string];
  navigate: [id: string];
  project: [id: string];
  "update:compact": [boolean];
  "update:bottom": [string];
  "update:bottomHeight": [number];
  "update:right": [string];
  "update:rightWidth": [number];
}>();
const groups = [
  "工程工作台",
  "数据准备",
  "场景生成",
  "平衡分析",
  "保供优化",
  "成果管理",
  "专项研究",
  "系统管理",
];
function command(id: string) {
  return props.commands.find((c) => c.id === id);
}
let stop = () => {};
function resize(e: PointerEvent, axis: "bottom" | "right") {
  const start = axis === "bottom" ? e.clientY : e.clientX,
    size = axis === "bottom" ? props.bottomHeight : props.rightWidth;
  const move = (v: PointerEvent) => {
    const n = size + start - (axis === "bottom" ? v.clientY : v.clientX);
    if (axis === "bottom")
      emit(
        "update:bottomHeight",
        Math.max(180, Math.min(innerHeight * 0.65, n)),
      );
    else
      emit("update:rightWidth", Math.max(300, Math.min(innerWidth * 0.45, n)));
  };
  stop();
  stop = () => {
    window.removeEventListener("pointermove", move);
    window.removeEventListener("pointerup", stop);
  };
  window.addEventListener("pointermove", move);
  window.addEventListener("pointerup", stop, { once: true });
}
onBeforeUnmount(() => stop());
</script>
<template>
  <div class="engineering-layout" :class="{ compact, presentation }">
    <header class="engineering-title">
      <strong>▦ 末端保供型局域电力系统软件平台</strong
      ><span :title="project?.name">{{ project?.name || "未选择工程" }}</span
      ><small>v{{ project?.revision ?? "—" }}</small
      ><select
        aria-label="切换工程"
        :value="project?.id"
        :disabled="busy"
        @change="emit('project', ($event.target as HTMLSelectElement).value)"
      >
        <option v-for="p in projects" :key="p.id" :value="p.id">
          {{ p.name }}
        </option></select
      ><button
        title="保存工程 Ctrl+S"
        aria-label="保存工程"
        :disabled="!project || busy"
        @click="emit('command', 'project.save')"
      >
        ▣
      </button>
    </header>
    <div class="engineering-menu">
      <details v-for="menu in menus" :key="menu.label">
        <summary>{{ menu.label }}</summary>
        <div class="global-menu-popup">
          <template v-for="id in menu.ids" :key="id"
            ><button
              v-if="command(id)"
              :disabled="disabled(command(id)!)"
              :title="command(id)?.reason?.()"
              @click="
                emit('command', id);
                ($event.target as HTMLElement)
                  .closest('details')
                  ?.removeAttribute('open');
              "
            >
              {{ command(id)?.label }}<small>{{ command(id)?.shortcut }}</small>
            </button></template
          >
        </div>
      </details>
    </div>
    <div class="engineering-body">
      <aside class="engineering-sidebar" v-show="!presentation">
        <div class="navigation-caption">
          <strong>{{ compact ? "流程" : "工程进度" }}</strong
          ><button
            title="展开或收起工程导航"
            aria-label="切换工程导航"
            @click="emit('update:compact', !compact)"
          >
            ☰
          </button>
        </div>
        <nav aria-label="工程进度与业务菜单">
          <template v-for="(group, i) in groups" :key="group"
            ><details
              :open="
                i < 6 ||
                workspaces.find((w) => w.id === workspace)?.stage === group
              "
              v-if="workspaces.filter((w) => w.stage === group).length > 1"
            >
              <summary :title="progress[group]?.detail">
                <span class="stage-index">{{
                  i < 6 ? String(i).padStart(2, "0") : "＋"
                }}</span
                ><span class="nav-label">{{ stageDisplayNames[group]||group }}</span
                ><small
                  v-if="progress[group]"
                  :class="['progress-state', progress[group].tone]"
                  >{{ progress[group].label }}</small
                >
              </summary>
              <button
                v-for="w in workspaces.filter((w) => w.stage === group)"
                :key="w.id"
                :title="w.label"
                :class="{ current: workspace === w.id }"
                @click="emit('navigate', w.id)"
              >
                <span>{{ w.icon }}</span
                ><span class="nav-label">{{ w.label }}</span>
              </button>
            </details>
            <button
              v-else
              v-for="w in workspaces.filter((w) => w.stage === group)"
              :key="w.id"
              class="single-workspace"
              :title="progress[group]?.detail || w.label"
              :class="{ current: workspace === w.id }"
              @click="emit('navigate', w.id)"
            >
              <span class="stage-index">{{
                i === 0 ? "⌂" : String(i).padStart(2, "0")
              }}</span
              ><span class="nav-label">{{ w.label }}</span
              ><small
                v-if="progress[group]"
                :class="['progress-state', progress[group].tone]"
                >{{ progress[group].label }}</small
              >
            </button></template
          >
        </nav>
        <span class="offline-label">本地工程工作空间</span>
      </aside>
      <div class="engineering-center">
        <div class="engineering-toolbar">
          <span class="workspace-name">{{
            workspaces.find((w) => w.id === workspace)?.label
          }}</span
          ><slot name="toolbar" /><button
            v-for="c in commands
              .filter((c) => !c.visible || c.visible())
              .filter((c) => c.surface === 'context')"
            :key="c.id"
            :class="{ primary: c.primary }"
            :title="disabled(c) ? c.reason?.() : c.label"
            :disabled="disabled(c)"
            @click="emit('command', c.id)"
          >
            <span v-if="c.icon" aria-hidden="true">{{c.icon}} </span>{{ c.label }}
          </button>
        </div>
        <div class="engineering-split">
          <main class="workspace-canvas"><slot /></main>
          <div
            v-if="right"
            class="right-resizer"
            @pointerdown.prevent="resize($event, 'right')"
          />
          <aside
            v-if="right"
            class="engineering-right"
            :style="{ width: rightWidth + 'px' }"
          >
            <div class="dock-heading">
              <strong>{{ right }}</strong
              ><button @click="emit('update:right', '')">关闭</button>
            </div>
            <slot name="right" />
          </aside>
        </div>
        <div
          v-if="bottom"
          class="engineering-bottom"
          :style="{ height: bottomHeight + 'px' }"
        >
          <div
            class="bottom-resizer"
            @pointerdown.prevent="resize($event, 'bottom')"
          />
          <div class="dock-heading">
            <div class="dock-tabs">
              <button
                v-for="t in ['计算任务', '数据明细', '校验信息', '分阶段指标']"
                :class="{ current: bottom === t }"
                @click="emit('update:bottom', t)"
              >
                {{ t }}
              </button>
            </div>
            <button
              title="关闭底部面板，不中断任务"
              @click="emit('update:bottom', '')"
            >
              关闭
            </button>
          </div>
          <div class="dock-content"><slot name="bottom" /></div>
        </div>
      </div>
    </div>
    <footer class="engineering-status">
      <span :class="busy ? 'running' : 'done'"
        >● {{ busy ? "处理中" : "就绪" }}</span
      ><span>{{ status }}</span
      ><span>工程 v{{ project?.revision ?? "—" }}</span>
    </footer>
  </div>
</template>
