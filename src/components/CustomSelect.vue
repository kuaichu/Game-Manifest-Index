<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from "vue";

export interface SelectOption {
  label: string;
  value: string | number | boolean | null;
  disabled?: boolean;
  kind?: string;
}

const props = withDefaults(
  defineProps<{
    modelValue?: string | number | boolean | null;
    options: Array<SelectOption | string>;
    placeholder?: string;
    disabled?: boolean;
    size?: "normal" | "small";
  }>(),
  {
    modelValue: "",
    placeholder: "请选择...",
    disabled: false,
    size: "normal",
  },
);

const emit = defineEmits<{
  (e: "update:modelValue", val: any): void;
  (e: "change", val: any): void;
}>();

const isOpen = ref(false);
const containerRef = ref<HTMLElement | null>(null);

const normalizedOptions = computed<SelectOption[]>(() =>
  props.options.map((opt) => {
    if (typeof opt === "string") {
      return { label: opt, value: opt };
    }
    return opt;
  }),
);

const selectedOption = computed(() =>
  normalizedOptions.value.find((opt) => opt.value === props.modelValue) || null,
);

const displayLabel = computed(() => {
  if (selectedOption.value) {
    return selectedOption.value.label;
  }
  if (props.modelValue === "" || props.modelValue === null || props.modelValue === undefined) {
    return props.placeholder;
  }
  return String(props.modelValue);
});

function toggle(): void {
  if (props.disabled) return;
  isOpen.value = !isOpen.value;
}

function selectOption(opt: SelectOption): void {
  if (opt.disabled) return;
  emit("update:modelValue", opt.value);
  emit("change", opt.value);
  isOpen.value = false;
}

function handleDocClick(e: MouseEvent): void {
  if (!containerRef.value) return;
  if (!containerRef.value.contains(e.target as Node)) {
    isOpen.value = false;
  }
}

function handleKeydown(e: KeyboardEvent): void {
  if (e.key === "Escape" && isOpen.value) {
    isOpen.value = false;
  }
}

onMounted(() => {
  document.addEventListener("click", handleDocClick);
  document.addEventListener("keydown", handleKeydown);
});

onBeforeUnmount(() => {
  document.removeEventListener("click", handleDocClick);
  document.removeEventListener("keydown", handleKeydown);
});
</script>

<template>
  <div
    ref="containerRef"
    class="custom-select-wrap"
    :class="[size, { 'is-open': isOpen, 'is-disabled': disabled }]"
  >
    <button
      class="custom-select-trigger"
      type="button"
      :disabled="disabled"
      @click="toggle"
    >
      <span class="trigger-label" :class="{ 'is-placeholder': !selectedOption && !modelValue }">
        {{ displayLabel }}
      </span>
      <svg class="select-chevron" :class="{ open: isOpen }" viewBox="0 0 24 24" aria-hidden="true">
        <path d="m6 9 6 6 6-6" />
      </svg>
    </button>

    <transition name="select-dropdown">
      <div v-if="isOpen" class="custom-select-popover">
        <div class="custom-select-scroll">
          <button
            v-for="(opt, idx) in normalizedOptions"
            :key="idx"
            class="custom-select-option"
            :class="{
              selected: opt.value === modelValue,
              disabled: opt.disabled,
            }"
            type="button"
            :disabled="opt.disabled"
            @click="selectOption(opt)"
          >
            <span class="option-label-text">{{ opt.label }}</span>
            <span v-if="opt.value === modelValue" class="option-check">✔</span>
          </button>
        </div>
      </div>
    </transition>
  </div>
</template>

<style scoped>
.custom-select-wrap {
  position: relative;
  width: 100%;
  user-select: none;
}

.custom-select-trigger {
  width: 100%;
  min-height: 40px;
  padding: 0 12px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  border-radius: 8px;
  border: 1px solid var(--line, rgba(255, 255, 255, 0.12));
  background: var(--panel-deep, #0b0f19);
  color: var(--text, #f8fafc);
  font-size: 13.5px;
  text-align: left;
  cursor: pointer;
  transition: all 0.15s cubic-bezier(0.16, 1, 0.3, 1);
}

.custom-select-wrap.small .custom-select-trigger {
  min-height: 34px;
  font-size: 12.5px;
  padding: 0 10px;
}

.custom-select-trigger:hover:not(:disabled) {
  border-color: var(--blue, #38bdf8);
  background: rgba(15, 23, 42, 0.9);
  box-shadow: 0 0 12px rgba(56, 189, 248, 0.15);
}

.custom-select-wrap.is-open .custom-select-trigger {
  border-color: var(--blue, #38bdf8);
  box-shadow: 0 0 0 3px var(--blue-glow, rgba(56, 189, 248, 0.25));
  background: rgba(15, 23, 42, 0.95);
}

.custom-select-wrap.is-disabled .custom-select-trigger {
  opacity: 0.5;
  cursor: not-allowed;
}

.trigger-label {
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  flex: 1;
}

.trigger-label.is-placeholder {
  color: var(--muted, #94a3b8);
}

.select-chevron {
  width: 14px;
  height: 14px;
  fill: none;
  stroke: var(--muted, #94a3b8);
  stroke-width: 2.2;
  stroke-linecap: round;
  stroke-linejoin: round;
  transition: transform 0.2s cubic-bezier(0.16, 1, 0.3, 1), stroke 0.16s ease;
  flex-shrink: 0;
}

.select-chevron.open {
  transform: rotate(180deg);
  stroke: var(--blue, #38bdf8);
}

.custom-select-popover {
  position: absolute;
  top: calc(100% + 5px);
  left: 0;
  right: 0;
  z-index: 300;
  background: rgba(11, 15, 25, 0.97);
  backdrop-filter: blur(20px);
  -webkit-backdrop-filter: blur(20px);
  border: 1px solid rgba(56, 189, 248, 0.28);
  border-radius: 10px;
  box-shadow: 0 16px 36px rgba(0, 0, 0, 0.7), 0 0 0 1px rgba(255, 255, 255, 0.05);
  padding: 6px;
  overflow: hidden;
}

.custom-select-scroll {
  max-height: 380px;
  overflow-y: auto;
  overflow-x: hidden;
  display: flex;
  flex-direction: column;
  gap: 2px;
  scrollbar-width: thin;
  scrollbar-color: rgba(56, 189, 248, 0.35) transparent;
}

.custom-select-scroll::-webkit-scrollbar {
  width: 4px;
  height: 4px;
}

.custom-select-scroll::-webkit-scrollbar-track {
  background: transparent;
}

.custom-select-scroll::-webkit-scrollbar-thumb {
  background: rgba(56, 189, 248, 0.35);
  border-radius: 999px;
}

.custom-select-scroll::-webkit-scrollbar-thumb:hover {
  background: rgba(56, 189, 248, 0.7);
}

.custom-select-scroll::-webkit-scrollbar-button {
  display: none;
  width: 0;
  height: 0;
}

.custom-select-option {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 7px 10px;
  border-radius: 6px;
  border: 1px solid transparent;
  background: transparent;
  color: #f1f5f9;
  font-size: 13px;
  text-align: left;
  width: 100%;
  cursor: pointer;
  transition: all 0.12s ease;
}

.custom-select-option:hover:not(:disabled) {
  background: rgba(56, 189, 248, 0.12);
  border-color: rgba(56, 189, 248, 0.2);
  color: #fff;
}

.custom-select-option.selected {
  background: rgba(56, 189, 248, 0.18);
  border-color: rgba(56, 189, 248, 0.4);
  font-weight: 600;
  color: #38bdf8;
}

.custom-select-option.disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.option-label-text {
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  flex: 1;
}

.option-check {
  font-size: 12px;
  color: #38bdf8;
  font-weight: 900;
}

.select-dropdown-enter-active,
.select-dropdown-leave-active {
  transition: all 0.15s cubic-bezier(0.16, 1, 0.3, 1);
}

.select-dropdown-enter-from,
.select-dropdown-leave-to {
  opacity: 0;
  transform: translateY(-4px) scale(0.98);
}
</style>
