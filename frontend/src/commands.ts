import { ref } from "vue";
export interface Command {
  id: string;
  label: string;
  icon?: string;
  surface?: "context" | "global";
  execute: () => unknown | Promise<unknown>;
  visible?: () => boolean;
  enabled?: () => boolean;
  reason?: () => string;
  shortcut?: string;
  primary?: boolean;
}
export function useCommands(
  definitions: Command[],
  onError: (message: string) => void,
) {
  const running = ref<string[]>([]);
  const available = () => definitions.filter((c) => !c.visible || c.visible());
  const disabled = (c: Command) =>
    running.value.includes(c.id) || (c.enabled ? !c.enabled() : false);
  async function execute(id: string) {
    const c = definitions.find((c) => c.id === id);
    if (!c || disabled(c) || (c.visible && !c.visible())) return;
    running.value = [...running.value, id];
    try {
      await c.execute();
    } catch (e) {
      onError(String(e));
    } finally {
      running.value = running.value.filter((v) => v !== id);
    }
  }
  return { available, disabled, execute, running };
}
