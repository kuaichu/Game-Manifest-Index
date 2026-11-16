import { ref } from "vue";
import { adminApi } from "../api";
import { externalScheduleNotice } from "../admin-ui-capabilities";
import type {
  ProbeSchedule,
  ProbeSchedulerStatus,
  ProbeStatus,
  SyncRunStatus,
  SyncSchedule,
} from "../types";
import type { AdminShell } from "./admin-shell";

export function useAdminProbe(shell: AdminShell) {
  const { token, authenticated, tab, error, success, askConfirm, withLoading, showError } = shell;

  const probeStatus = ref<ProbeStatus | null>(null);
  const probeSchedule = ref<ProbeSchedule>({ enabled: false, interval_hours: 24, mode: "normal" });
  const probeSchedulerStatus = ref<ProbeSchedulerStatus | null>(null);
  let probePollTimer: number | null = null;

  async function loadProbeStatus(): Promise<void> {
    try {
      probeStatus.value = await adminApi.probeStatus(token.value.trim());
    } catch (reason) {
      if (!(reason instanceof DOMException && reason.name === "AbortError")) showError(reason);
    }
  }

  async function loadProbeSchedulerStatus(): Promise<void> {
    try {
      probeSchedulerStatus.value = await adminApi.probeScheduler(token.value.trim());
    } catch (reason) {
      probeSchedulerStatus.value = null;
      if (!(reason instanceof DOMException && reason.name === "AbortError")) showError(reason);
    }
  }

  function startProbePolling(): void {
    stopProbePolling();
    probePollTimer = window.setInterval(async () => {
      if (!authenticated.value || tab.value !== "probe") return;
      await loadProbeStatus();
      await loadProbeSchedulerStatus();
      await loadSyncRunStatus();
    }, 2500);
  }

  function stopProbePolling(): void {
    if (probePollTimer !== null) {
      window.clearInterval(probePollTimer);
      probePollTimer = null;
    }
  }

  async function openProbe(): Promise<void> {
    tab.value = "probe";
    await loadProbeStatus();
    await loadProbeSchedulerStatus();
    await loadSyncRunStatus();
    try {
      probeSchedule.value = await adminApi.probeSchedule(token.value.trim());
    } catch (reason) {
      if (!(reason instanceof DOMException && reason.name === "AbortError")) showError(reason);
    }
    try {
      const fetchedSyncSchedule = await adminApi.syncSchedule(token.value.trim());
      if (fetchedSyncSchedule) {
        const times = Array.isArray(fetchedSyncSchedule.times) ? [...fetchedSyncSchedule.times] : ["04:45", "14:00"];
        while (times.length < 2) times.push("");
        syncSchedule.value = {
          enabled: Boolean(fetchedSyncSchedule.enabled),
          times,
        };
      }
    } catch (reason) {
      if (!(reason instanceof DOMException && reason.name === "AbortError")) showError(reason);
    }
    startProbePolling();
  }

  async function saveProbeSchedule(): Promise<void> {
    const confirmed = await askConfirm("确定要保存并更新下载链接探活策略吗？");
    if (!confirmed) return;
    await withLoading(async (signal) => {
      probeSchedule.value = await adminApi.saveProbeSchedule(probeSchedule.value, token.value, signal);
      await loadProbeSchedulerStatus();
      success.value = "定时探活计划已保存。";
    });
  }

  const syncRunStatus = ref<SyncRunStatus | null>(null);

  async function loadSyncRunStatus(): Promise<void> {
    if (!authenticated.value) return;
    try {
      syncRunStatus.value = await adminApi.syncRunStatus(token.value.trim());
    } catch {
      // optional status
    }
  }

  const syncSchedule = ref<SyncSchedule>({ enabled: true, times: ["04:45", "14:00"] });

  async function saveSyncSchedule(): Promise<void> {
    const validTimes = (syncSchedule.value?.times || [])
      .map((item) => (item || "").trim())
      .filter(Boolean);

    if (syncSchedule.value.enabled && validTimes.length === 0) {
      error.value = "请至少配置一个有效的每日采集时间点（例如 04:45）";
      return;
    }

    const confirmed = await askConfirm(`确定要保存每日采集计划（时间点: ${validTimes.join(", ")}）吗？`);
    if (!confirmed) return;

    await withLoading(async (signal) => {
      const payload: SyncSchedule = {
        enabled: syncSchedule.value.enabled,
        times: validTimes,
      };
      const saved = await adminApi.saveSyncSchedule(payload, token.value, signal);
      const times = Array.isArray(saved.times) ? [...saved.times] : validTimes;
      while (times.length < 2) times.push("");
      syncSchedule.value = {
        enabled: saved.enabled,
        times,
      };
      success.value = `采集计划参数已保存。${externalScheduleNotice}`;
    });
  }

  return {
    probeStatus,
    probeSchedule,
    probeSchedulerStatus,
    syncRunStatus,
    syncSchedule,
    loadProbeStatus,
    loadSyncRunStatus,
    stopProbePolling,
    openProbe,
    saveProbeSchedule,
    saveSyncSchedule,
  };
}

export type AdminProbe = ReturnType<typeof useAdminProbe>;
