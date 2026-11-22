import { ref, watch } from "vue";
const key = "terminal-power.layout.v2";
export function useLayoutPreferences() {
  let saved: any = {};
  try {
    saved = JSON.parse(localStorage.getItem(key) || "{}");
  } catch {}
  const compact = ref(!!saved.compact),
    rightWidth = ref(
      Math.min(480, Math.max(300, Number(saved.rightWidth) || 340)),
    ),
    bottomHeight = ref(
      Math.min(500, Math.max(180, Number(saved.bottomHeight) || 260)),
    );
  const presentation = ref(false),
    right = ref(""),
    bottom = ref("");
  watch([compact, rightWidth, bottomHeight], () =>
    localStorage.setItem(
      key,
      JSON.stringify({
        compact: compact.value,
        rightWidth: rightWidth.value,
        bottomHeight: bottomHeight.value,
      }),
    ),
  );
  function reset() {
    compact.value = false;
    rightWidth.value = 340;
    bottomHeight.value = 260;
    presentation.value = false;
    right.value = "";
    bottom.value = "";
  }
  return {
    compact,
    rightWidth,
    bottomHeight,
    presentation,
    right,
    bottom,
    reset,
  };
}
