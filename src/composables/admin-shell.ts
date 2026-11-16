import type { ComputedRef, Ref } from "vue";
import type { ConfirmDialogRequest } from "../components/admin/AdminConfirmDialog.vue";
import type { AdminCatalog, AdminDomain } from "../types";

export type AdminTab = "games" | "domains" | "content" | "probe";

// AdminView owns this shared state; the admin composables read and write it.
export interface AdminShell {
  token: Ref<string>;
  authenticated: Ref<boolean>;
  catalog: Ref<AdminCatalog>;
  tab: Ref<AdminTab>;
  loading: Ref<boolean>;
  error: Ref<string>;
  success: Ref<string>;
  selectedGameId: Ref<string>;
  selectedDomainId: Ref<string>;
  gameDomains: ComputedRef<AdminDomain[]>;
  askConfirm: (
    message: string,
    options?: Partial<Omit<ConfirmDialogRequest, "message">>,
  ) => Promise<boolean>;
  withLoading: (action: (signal: AbortSignal) => Promise<void>) => Promise<void>;
  showError: (reason: unknown) => void;
  selectGame: (id: string) => void;
  selectDomain: (id: string) => void;
}
