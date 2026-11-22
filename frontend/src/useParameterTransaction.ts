import { watch, onBeforeUnmount, type Ref } from "vue";
/** Local form transaction. Submitting a task may accept its input without closing. */
export function useParameterTransaction(
  open: Ref<boolean>,
  fields: Record<string, Ref<any>>,
) {
  let initial: Record<string, any> | null = null;
  const copy = (value: any) =>
    value === undefined ? undefined : JSON.parse(JSON.stringify(value));
  function capture() {
    return Object.fromEntries(
      Object.entries(fields).map(([key, value]) => [key, copy(value.value)]),
    );
  }
  const stop = watch(
    open,
    (value) => {
      if (value) initial = capture();
      else if (initial) {
        for (const [key, value] of Object.entries(initial))
          if (JSON.stringify(fields[key].value) !== JSON.stringify(value))
            fields[key].value = copy(value);
        initial = null;
      }
    },
    { flush: "sync" },
  );
  function commit(close = true) {
    if (initial) initial = capture();
    if (close) open.value = false;
  }
  onBeforeUnmount(() => {
    stop();
    initial = null;
  });
  return commit;
}
