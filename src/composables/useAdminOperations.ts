import { computed, ref } from "vue";
import { ApiError, adminApi } from "../api";
import {
  isProbeUnknownItem,
  operationControlsDisabled,
  operationScopeLabel,
  restoredOperationScope,
} from "../operation-scope";
import type {
  AdminOperationJob,
  AdminOperationPayload,
  AdminOperationResult,
} from "../types";
import type { AdminShell } from "./admin-shell";
import type { AdminProbe } from "./useAdminProbe";
import type { AvailabilityInvalidation } from "./useAvailabilityInvalidation";

const OPERATION_JOB_KEY = "game-manifest-index-web-operation-job-v1";
const OP_TERMINAL_LOG_LIMIT = 256;

type TerminalLogTone = "success" | "danger" | "warning" | "info";
type TerminalLogEntry = {
  id: number;
  raw: string;
  phase: string;
  target: string;
  outcome: string;
  tone: TerminalLogTone;
  detail: string;
};

export function terminalLogTone(outcome: string): TerminalLogTone {
  if (/失败|失效|错误|异常|取消/i.test(outcome)) return "danger";
  if (/未知|未判定|跳过|等待/i.test(outcome)) return "warning";
  if (/成功|可用|完成|正常/i.test(outcome)) return "success";
  return "info";
}

function parseTerminalLog(raw: string, id: number): TerminalLogEntry {
  const match = raw.match(/^\[([^\]]+)\]\s+(.+?)\s+(可用|不可用|未判定|未知|失败(?::.*)?|成功|跳过.*)$/u);
  if (!match) {
    return { id, raw, phase: "系统", target: "运维任务", outcome: "记录", tone: "info", detail: raw };
  }
  const [scope, target, outcome] = match.slice(1);
  const [phase, platform] = scope.split("/");
  return {
    id,
    raw,
    phase: phase === "probe" ? "探活" : phase === "discover" ? "发现" : phase,
    target: `${target}${platform ? ` · ${platform}` : ""}`,
    outcome: outcome.startsWith("失败:") ? "失败" : outcome,
    tone: terminalLogTone(outcome),
    detail: outcome.startsWith("失败:") ? outcome.slice(3) : "",
  };
}

export interface AdminOperationsDeps {
  probe: Pick<AdminProbe, "probeStatus" | "syncRunStatus" | "loadProbeStatus" | "loadSyncRunStatus">;
  availability: Pick<AvailabilityInvalidation, "notifyAvailabilityInvalidated">;
  refreshAllData: () => Promise<void>;
}

export function useAdminOperations(shell: AdminShell, deps: AdminOperationsDeps) {
  const { token, authenticated, catalog, loading, error, success, askConfirm, withLoading, showError } = shell;
  const { probeStatus, syncRunStatus, loadProbeStatus, loadSyncRunStatus } = deps.probe;
  const { notifyAvailabilityInvalidated } = deps.availability;
  const { refreshAllData } = deps;

  const opAction = ref<"both" | "discover">("both");
  const opScope = ref<"all" | "custom">("all");
  const opPlatformScope = ref<"all" | "android" | "pc">("all");
  const opSelectedGameIds = ref<string[]>([]);
  const opTimeout = ref<number>(10);
  const opWorkers = ref<number>(8);
  const opRunning = ref<boolean>(false);
  const opJob = ref<AdminOperationJob | null>(null);
  const opResult = ref<AdminOperationResult | null>(null);
  const opExecutionTime = ref<number | null>(null);
  const opTerminalLogs = ref<string[]>([]);

  const opLogOffset = ref(0);
  const opTerminalHidden = ref(false);
  let operationPollTimer: number | null = null;
  let operationPollBusy = false;


  const terminalLogSource = computed(() => {
    if (opTerminalLogs.value.length) return opTerminalLogs.value;
    const syncTail = syncRunStatus.value?.result?.log_tail;
    if (syncTail) return syncTail.split(/\r?\n/).filter(Boolean);
    return (probeStatus.value?.log || []).slice(-150);
  });

  const terminalLogEntries = computed<TerminalLogEntry[]>(() =>
    terminalLogSource.value.map((line, index) => parseTerminalLog(line, index + 1)),
  );

  const terminalLogStats = computed(() => terminalLogEntries.value.reduce(
    (stats, entry) => {
      stats.total += 1;
      if (entry.tone === "success") stats.success += 1;
      if (entry.tone === "danger") stats.danger += 1;
      if (entry.tone === "warning") stats.warning += 1;
      return stats;
    },
    { total: 0, success: 0, danger: 0, warning: 0 },
  ));

  const terminalStatusText = computed(() => {
    if (opJob.value?.status === "cancelling") return "正在取消";
    if (opRunning.value) return "执行中";
    if (opJob.value?.status === "finished") return "已完成";
    if (opJob.value?.status === "failed") return "执行失败";
    if (opJob.value?.status === "cancelled") return "已取消";
    if (probeStatus.value?.status === "running") return "探活中";
    return terminalLogEntries.value.length ? "最近记录" : "等待任务";
  });

  const operationScope = computed(() =>
    restoredOperationScope(opJob.value?.scope ?? opResult.value?.scope),
  );
  const operationScopeText = computed(() => operationScopeLabel(operationScope.value));
  const operationControlsLocked = computed(() =>
    operationControlsDisabled(loading.value, opJob.value?.status),
  );

  const probeTableFilter = ref<"all" | "available" | "unavailable" | "unknown" | "failed">("all");

  const filteredProbeItems = computed(() => {
    if (!opResult.value?.probe?.items) return [];
    const items = opResult.value.probe.items;
    if (probeTableFilter.value === "available") {
      return items.filter((it) => it.available === true);
    }
    if (probeTableFilter.value === "unavailable") {
      return items.filter((it) => it.available === false);
    }
    if (probeTableFilter.value === "unknown") {
      return items.filter(isProbeUnknownItem);
    }
    if (probeTableFilter.value === "failed") {
      return items.filter((it) => it.ok === false);
    }
    return items;
  });

  const opProgressPercent = computed(() => {
    const total = opJob.value?.total || 0;
    return total > 0 ? Math.min(100, Math.round(((opJob.value?.completed || 0) / total) * 100)) : 0;
  });

  const opCurrentGameLabel = computed(() => {
    const gameId = opJob.value?.current?.game_id;
    return gameId ? gameDisplayName(gameId) : "";
  });

  function stopOperationPolling(): void {
    if (operationPollTimer !== null) {
      window.clearInterval(operationPollTimer);
      operationPollTimer = null;
    }
  }

  async function applyOperationJob(job: AdminOperationJob, isInitialRestore = false, incremental = false): Promise<void> {
    const sameJob = opJob.value?.job_id === job.job_id;
    opJob.value = job;
    const restoredScope = restoredOperationScope(job.scope ?? job.result?.scope);
    if (restoredScope) opPlatformScope.value = restoredScope;
    opRunning.value = job.status === "running" || job.status === "cancelling";
    if (incremental && sameJob) {
      opTerminalLogs.value = [...opTerminalLogs.value, ...(job.logs || [])].slice(-OP_TERMINAL_LOG_LIMIT);
      opLogOffset.value = job.log_total ?? (opLogOffset.value + (job.logs || []).length);
      if (job.logs?.length) opTerminalHidden.value = false;
    } else {
      opTerminalLogs.value = (job.logs || []).slice(-OP_TERMINAL_LOG_LIMIT);
      opLogOffset.value = job.log_total ?? ((job.log_offset ?? 0) + (job.logs?.length || 0));
      opTerminalHidden.value = false;
    }
    if (opRunning.value) return;

    stopOperationPolling();
    sessionStorage.removeItem(OPERATION_JOB_KEY);
    if (job.result) {
      probeTableFilter.value = "all";
      opResult.value = job.result;
      if (job.started_at && job.finished_at) {
        const start = new Date(job.started_at).getTime();
        const end = new Date(job.finished_at).getTime();
        opExecutionTime.value = Math.max(0, Math.round((end - start) / 100) / 10);
      }
    }
    if (!isInitialRestore) {
      if (job.status === "finished") {
        success.value = "运维操作已全部执行完成！";
        if (job.actions.includes("probe")) notifyAvailabilityInvalidated(job.job_id);
        await refreshAllData();
      } else if (job.status === "cancelled") {
        error.value = "运维操作已被管理员手动取消。";
      } else if (job.status === "failed") {
        error.value = `运维操作执行失败：${job.error || "未知异常"}`;
      }
    }
  }

  async function pollAdminOperation(jobId: string, initial = false): Promise<void> {
    if (operationPollBusy || !authenticated.value) return;
    operationPollBusy = true;
    try {
      const after = initial || opJob.value?.job_id !== jobId ? undefined : opLogOffset.value;
      try {
        await applyOperationJob(await adminApi.operationStatus(jobId, token.value.trim(), undefined, after), initial, after !== undefined);
      } catch (reason) {
        // A stale cursor (or a service-side log reset) is recovered with a full snapshot.
        if (reason instanceof ApiError && reason.status === 422 && after !== undefined) {
          await applyOperationJob(await adminApi.operationStatus(jobId, token.value.trim()), initial, false);
        } else {
          throw reason;
        }
      }
    } catch (reason) {
      stopOperationPolling();
      sessionStorage.removeItem(OPERATION_JOB_KEY);
      showError(reason);
    } finally {
      operationPollBusy = false;
    }
  }

  function startOperationPolling(jobId: string): void {
    stopOperationPolling();
    operationPollTimer = window.setInterval(() => void pollAdminOperation(jobId), 1000);
  }

  async function resumeAdminOperation(): Promise<void> {
    if (!authenticated.value) return;
    const jobId = sessionStorage.getItem(OPERATION_JOB_KEY);
    if (jobId) {
      await pollAdminOperation(jobId, true);
      if (opRunning.value) startOperationPolling(jobId);
      return;
    }
    if (!opResult.value && !opRunning.value) {
      try {
        const latestJob = await adminApi.latestOperation(token.value.trim());
        if (latestJob) {
          await applyOperationJob(latestJob, true);
        }
      } catch {
        // 忽略未找到历史记录
      }
    }
  }

  function toggleGameSelection(gameId: string): void {
    const index = opSelectedGameIds.value.indexOf(gameId);
    if (index >= 0) {
      opSelectedGameIds.value.splice(index, 1);
    } else {
      opSelectedGameIds.value.push(gameId);
    }
  }

  function selectAllGames(): void {
    opSelectedGameIds.value = catalog.value.games.map((g) => g.id);
  }

  function clearSelectedGames(): void {
    opSelectedGameIds.value = [];
  }

  function isGameSelected(gameId: string): boolean {
    return opSelectedGameIds.value.includes(gameId);
  }

  function appendOpLog(line: string): void {
    opTerminalHidden.value = false;
    opTerminalLogs.value.push(line);
    if (opTerminalLogs.value.length > OP_TERMINAL_LOG_LIMIT) {
      opTerminalLogs.value = opTerminalLogs.value.slice(-OP_TERMINAL_LOG_LIMIT);
    }
  }

  async function refreshTerminalLogs(): Promise<void> {
    if (operationPollBusy || !authenticated.value) return;
    operationPollBusy = true;
    try {
      const jobId = opJob.value?.job_id;
      const job = jobId
        ? await adminApi.operationStatus(jobId, token.value.trim())
        : await adminApi.latestOperation(token.value.trim());
      await applyOperationJob(job, false, false);
      await Promise.all([loadProbeStatus(), loadSyncRunStatus()]);
    } catch (reason) {
      showError(reason);
    } finally {
      operationPollBusy = false;
    }
  }

  function clearOpResult(): void {
    opResult.value = null;
    opExecutionTime.value = null;
    probeTableFilter.value = "all";
  }

  function gameDisplayName(gameId: string): string {
    const item = catalog.value.games.find((g) => g.id === gameId);
    return item ? `${item.name} (${item.id})` : gameId;
  }

  async function executeAdminOperation(): Promise<void> {
    const actions: ("discover" | "probe")[] =
      opAction.value === "discover" ? ["discover"] : ["discover", "probe"];

    if (opScope.value === "custom" && opSelectedGameIds.value.length === 0) {
      error.value = "请至少勾选一款游戏，或切换为【全部游戏】模式。";
      return;
    }

    const payload: AdminOperationPayload = {
      actions,
      scope: opPlatformScope.value,
      all_games: opScope.value === "all",
      game_ids: opScope.value === "custom" ? [...opSelectedGameIds.value] : undefined,
      timeout: Math.max(1, Math.min(60, Number(opTimeout.value) || 10)),
      workers: Math.max(1, Math.min(16, Number(opWorkers.value) || 8)),
    };

    const actionText =
      opAction.value === "discover"
        ? "【仅查找新版本 (discover)】"
        : "【查找新版本 + 探活全量 (discover + probe)】";
    const scopeText =
      opScope.value === "all"
        ? `全部 ${catalog.value.games.length || "已注册"} 款游戏`
        : `${opSelectedGameIds.value.length} 款指定游戏（${opSelectedGameIds.value.join(", ")}）`;
    const platformText =
      opPlatformScope.value === "all"
        ? "全量数据 (APK + PC)"
        : opPlatformScope.value === "android"
        ? "仅 Android (APK 直链)"
        : "仅 PC 客户端 (Windows)";

    const confirmed = await askConfirm(
      `确定要启动 ${actionText} 操作吗？\n目标范围：${scopeText}\n数据类型：${platformText}\n启动后可查看实时进度，也可以取消未开始的任务。`,
      { title: "启动运维任务", confirmLabel: "启动" },
    );
    if (!confirmed) return;

    opRunning.value = true;
    opResult.value = null;
    opExecutionTime.value = null;
    probeTableFilter.value = "all";
    error.value = "";
    success.value = "";

    const timeStr = new Date().toLocaleTimeString();
    appendOpLog(`[${timeStr}] 启动运维操作 POST /api/v1/admin/operations/start`);
    appendOpLog(`[${timeStr}] 动作: [${actions.join(", ")}] | 数据范围: ${operationScopeLabel(payload.scope)} | 游戏范围: ${opScope.value === "all" ? "全部游戏 (all_games=true)" : opSelectedGameIds.value.join(", ")} | 超时: ${payload.timeout}s | 并发: ${payload.workers}`);

    await withLoading(async (signal) => {
      try {
        const job = await adminApi.startOperation(payload, token.value.trim(), signal);
        sessionStorage.setItem(OPERATION_JOB_KEY, job.job_id);
        await applyOperationJob(job);
        if (opRunning.value) startOperationPolling(job.job_id);
      } catch (err) {
        const finishTime = new Date().toLocaleTimeString();
        appendOpLog(`[${finishTime}] ✕ 运维操作请求失败: ${err instanceof Error ? err.message : "未知错误"}`);
        opRunning.value = false;
        throw err;
      }
    });
  }

  async function cancelAdminOperation(): Promise<void> {
    const jobId = opJob.value?.job_id;
    if (
      !jobId ||
      !(await askConfirm("确定要取消当前运维任务吗？已完成的数据会保留。", {
        title: "取消运维任务",
        confirmLabel: "取消任务",
      }))
    )
      return;
    try {
      await applyOperationJob(await adminApi.cancelOperation(jobId, token.value.trim()));
      if (opRunning.value) startOperationPolling(jobId);
    } catch (reason) {
      showError(reason);
    }
  }

  // The poll-busy flag is deliberately not reactive (it never was); the template reads it at render time.
  function isOperationPollBusy(): boolean {
    return operationPollBusy;
  }

  return {
    opAction,
    opScope,
    opPlatformScope,
    opSelectedGameIds,
    opTimeout,
    opWorkers,
    opRunning,
    opJob,
    opResult,
    opExecutionTime,
    opTerminalHidden,
    probeTableFilter,
    filteredProbeItems,
    operationControlsLocked,
    operationScopeText,
    opProgressPercent,
    opCurrentGameLabel,
    terminalLogEntries,
    terminalLogStats,
    terminalStatusText,
    terminalLogTone,
    gameDisplayName,
    selectAllGames,
    clearSelectedGames,
    isGameSelected,
    toggleGameSelection,
    refreshTerminalLogs,
    clearOpResult,
    executeAdminOperation,
    cancelAdminOperation,
    isOperationPollBusy,
    stopOperationPolling,
    resumeAdminOperation,
  };
}

export type AdminOperations = ReturnType<typeof useAdminOperations>;
