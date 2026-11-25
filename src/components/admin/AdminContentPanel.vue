<script setup lang="ts">
import AdminApkArtifactCard from "./AdminApkArtifactCard.vue";
import AdminPcArtifactsCard from "./AdminPcArtifactsCard.vue";
import AdminVersionBasicCard from "./AdminVersionBasicCard.vue";
import AdminVersionList from "./AdminVersionList.vue";
import { formatBytes, formatSyncTime } from "../../admin-format";
import { getDomainFriendlyName } from "../../admin-version-editor";
import type { AdminContent } from "../../composables/useAdminContent";
import type { AdminDomain } from "../../types";

const props = defineProps<{
  content: AdminContent;
  loading: boolean;
  selectedGameId: string;
  selectedDomainId: string;
  gameDomains: AdminDomain[];
  resolveGameIcon: (id: string, source?: string) => string | undefined;
}>();

// The content state lives in AdminView (via useAdminContent) so it survives tab switches.
const {
  versionList,
  contentSubTab,
  editableLoaded,
  editableLoading,
  checksumsOpen,
  moreActionsOpen,
  editableDraft,
  createDraft,
  versionDraft,
  isCreateMode,
  selectedDomainSupportsCreateVersion,
  selectedDomainUsesPcEditor,
  selectedDomainSupportsManualVersion,
  currentVersionHealth,
  pcArtifactsOverview,
  isUrlChanged,
  dirtyChangesCount,
  isEditableDirty,
  showApkFileCard,
  fileTimeRaw,
  fileTimeInputValue,
  fileTimeLabel,
  fileTimeUnparsable,
  urlProbeMap,
  clearActiveFileTime,
  copyUrl,
  openUrl,
  onFileTimeInput,
  submitVersionForm,
  preventEnterSubmit,
  addArtifactItem,
  removeArtifactItem,
  addArtifactUrlItem,
  removeArtifactUrlItem,
  handleArtifactUrlChange,
  forceExtractArtifactName,
  switchArtifactsMode,
  formatArtifactsJson,
  probeUrlItem,
  handleActiveArtifactUrlChange,
  forceExtractActiveArtifactName,
  syncArtifactsToJson,
  syncArtifactsJsonForActiveDraft,
  onContentVersionSelect,
  discardChanges,
  toggleVersionVisibility,
  deleteCurrentVersion,
  copyCurrentVersionToCreateDraft,
  resetCreateDraft,
  probeCurrentVersion,
} = props.content;
const { selectedVersion, selectedDomainGameName, selectedDomain } = versionList;
</script>

<template>
  <section class="admin-content-grid">
    <AdminVersionList
      :version-list="versionList"
      :selected-game-id="selectedGameId"
      :selected-domain-id="selectedDomainId"
      :game-domains="gameDomains"
      :resolve-game-icon="resolveGameIcon"
      @select-version="onContentVersionSelect"
    >
      <!-- 右侧：版本工作台（编辑版本 / 新建版本） -->
      <div v-if="selectedDomainSupportsManualVersion" class="content-work-card">
        <!-- 子功能切换 Tab -->
        <div class="content-sub-tabs">
          <button
            class="sub-tab-btn"
            :class="{ active: contentSubTab === 'edit' }"
            type="button"
            @click="contentSubTab = 'edit'"
          >
            <span>编辑版本</span>
          </button>
          <button
            v-if="selectedDomainSupportsCreateVersion"
            class="sub-tab-btn"
            :class="{ active: contentSubTab === 'create' }"
            type="button"
            @click="contentSubTab = 'create'"
          >
            <span>新建版本</span>
          </button>
        </div>

        <!-- 版本工作台：编辑与新建共用同一套字段与资源编辑器 -->
        <form
          class="version-edit-form"
          :class="{ 'version-create-form': isCreateMode }"
          novalidate
          @keydown.enter="preventEnterSubmit"
          @submit.prevent="submitVersionForm"
        >
          <!-- 顶部版本状态栏 -->
          <div class="version-status-topbar">
            <div class="version-header-meta">
              <div class="version-title-row">
                <template v-if="isCreateMode">
                  <h2>新建版本 · {{ selectedDomainGameName }} <span class="divider">/</span> {{ getDomainFriendlyName(selectedDomain) }}</h2>
                  <span class="status-pill success">新建模式</span>
                </template>
                <template v-else>
                  <h2>{{ selectedDomainGameName }} <span class="divider">/</span> {{ getDomainFriendlyName(selectedDomain) }} <span class="divider">/</span> {{ selectedVersion || '未选择版本' }}</h2>
                  <span v-if="!editableDraft.is_visible" class="status-pill hidden">已隐藏</span>
                </template>
              </div>
            </div>

            <div class="version-header-actions">
              <template v-if="isCreateMode">
                <button
                  v-if="selectedVersion && editableLoaded"
                  class="admin-btn secondary"
                  type="button"
                  @click="copyCurrentVersionToCreateDraft"
                >
                  <span>复制当前 ({{ selectedVersion }}) 为模板</span>
                </button>
                <button
                  class="admin-btn secondary"
                  type="button"
                  @click="resetCreateDraft"
                >
                  <span>重置</span>
                </button>
              </template>
              <template v-else>
                <button
                  type="button"
                  class="admin-btn secondary"
                  :disabled="editableLoading || loading || !selectedVersion"
                  title="向官方源发起实时探活并持久化探活结果，不会保存当前表单草稿"
                  @click="probeCurrentVersion()"
                >
                  <span>实时探活</span>
                </button>

                <!-- 更多操作下拉菜单 -->
                <div class="custom-dropdown-container more-actions-dropdown">
                  <button
                    type="button"
                    class="admin-btn secondary"
                    title="更多操作"
                    @click.stop="moreActionsOpen = !moreActionsOpen"
                  >
                    <span>更多 ▾</span>
                  </button>
                  <transition name="dropdown-fade">
                    <div v-if="moreActionsOpen" class="more-dropdown-menu" @click.stop>
                      <button
                        type="button"
                        class="more-dropdown-item"
                        @click="toggleVersionVisibility(); moreActionsOpen = false"
                      >
                        <span>{{ editableDraft.is_visible ? '隐藏此版本' : '恢复公开' }}</span>
                      </button>
                      <button
                        v-if="selectedDomainSupportsCreateVersion"
                        type="button"
                        class="more-dropdown-item"
                        @click="copyCurrentVersionToCreateDraft(); moreActionsOpen = false"
                      >
                        <span>复制为新版本模板</span>
                      </button>
                      <hr class="more-divider" />
                      <button
                        type="button"
                        class="more-dropdown-item danger"
                        @click="deleteCurrentVersion(); moreActionsOpen = false"
                      >
                        <span>删除此版本</span>
                      </button>
                    </div>
                  </transition>
                </div>
              </template>
            </div>
          </div>

          <div v-if="!isCreateMode && !selectedVersion" class="admin-empty-state">
            请先在左侧列表中选择一个目标版本。
          </div>

          <template v-else>
            <!-- 链接健康条 (Health Banner - 紧凑低饱和)：仅编辑已有版本时展示 -->
            <div
              v-if="!isCreateMode"
              class="health-banner-card"
              :class="currentVersionHealth.isOk ? 'success' : (currentVersionHealth.isChecked ? 'danger' : 'neutral')"
            >
              <div class="banner-left">
                <span class="banner-dot">●</span>
                <strong class="banner-status">
                  {{ currentVersionHealth.isOk ? '链接可用' : (currentVersionHealth.isChecked ? '链接不可用' : '待探活') }}
                </strong>
                <span v-if="currentVersionHealth.httpCode" class="banner-badge">HTTP {{ currentVersionHealth.httpCode }}</span>
                <span v-if="currentVersionHealth.size" class="banner-badge">{{ formatBytes(currentVersionHealth.size) }}</span>
                <span v-if="currentVersionHealth.lastCheckedAt" class="banner-time">
                  最后检查：{{ formatSyncTime(currentVersionHealth.lastCheckedAt) }}
                </span>
              </div>
              <div class="banner-right">
                <button
                  v-if="!currentVersionHealth.isOk && currentVersionHealth.isChecked"
                  class="banner-action-btn"
                  type="button"
                  @click="probeCurrentVersion()"
                >
                  重新探活
                </button>
              </div>
            </div>

            <AdminVersionBasicCard
              :draft="versionDraft"
              :is-create-mode="isCreateMode"
              :file-time-raw="fileTimeRaw"
              :file-time-input-value="fileTimeInputValue"
              :file-time-label="fileTimeLabel"
              :file-time-unparsable="fileTimeUnparsable"
              @clear-file-time="clearActiveFileTime"
              @file-time-input="onFileTimeInput"
            />

            <AdminApkArtifactCard
              v-if="showApkFileCard"
              :draft="versionDraft"
              :checksums-open="checksumsOpen"
              :url-probe-map="urlProbeMap"
              @toggle-checksums="checksumsOpen = !checksumsOpen"
              @extract-name="forceExtractActiveArtifactName"
              @sync-json="syncArtifactsJsonForActiveDraft"
              @url-change="handleActiveArtifactUrlChange"
              @copy-url="copyUrl"
              @open-url="openUrl"
              @probe-url="probeUrlItem"
            />

            <AdminPcArtifactsCard
              v-if="selectedDomainUsesPcEditor"
              :draft="editableDraft"
              :overview="pcArtifactsOverview"
              :url-probe-map="urlProbeMap"
              @switch-mode="switchArtifactsMode"
              @format-json="formatArtifactsJson"
              @add-artifact="addArtifactItem"
              @remove-artifact="removeArtifactItem"
              @extract-name="forceExtractArtifactName"
              @sync-json="syncArtifactsToJson"
              @add-url="addArtifactUrlItem"
              @remove-url="removeArtifactUrlItem"
              @url-change="handleArtifactUrlChange"
              @copy-url="copyUrl"
              @probe-url="probeUrlItem"
            />

            <!-- 底部操作条：新建走提交，编辑走吸附保存 -->
            <div v-if="isCreateMode" class="form-actions-bar">
              <div class="actions-left">
                <button
                  type="button"
                  class="admin-btn secondary"
                  @click="resetCreateDraft"
                >
                  <span>重置表单</span>
                </button>
                <span v-if="!createDraft.version.trim()" class="create-submit-hint">
                  填写版本号后即可提交
                </span>
              </div>

              <div class="actions-right">
                <button
                  class="admin-btn primary"
                  type="submit"
                  :disabled="loading || !selectedDomainId || !createDraft.version.trim()"
                >
                  <span>{{ loading ? '录入中…' : '保存并录入新版本' }}</span>
                </button>
              </div>
            </div>
            <!-- 底部吸附保存交互条（唯一保存入口） -->
            <div v-else class="sticky-save-bar" :class="{ dirty: isEditableDirty }">
              <div class="bar-left">
                <span v-if="isEditableDirty" class="save-status-badge dirty">⚠ 有 {{ dirtyChangesCount }} 项未保存修改</span>
                <span v-else class="save-status-badge clean">● 没有未保存修改</span>
              </div>
              <div class="bar-right">
                <button
                  v-if="isEditableDirty"
                  class="admin-btn secondary small"
                  type="button"
                  @click="discardChanges"
                >
                  放弃修改
                </button>
                <button
                  class="admin-btn primary small"
                  type="submit"
                  :disabled="loading || !selectedVersion || !isEditableDirty"
                >
                  <span>{{ selectedDomainSupportsCreateVersion && isUrlChanged ? '保存并探活' : '保存更改' }}</span>
                </button>
              </div>
            </div>
          </template>
        </form>
      </div>
      <div v-else class="content-work-card">
        <div class="version-status-topbar">
          <div class="version-header-meta">
            <div class="version-title-row"><h2>PC 版本只读</h2></div>
          </div>
        </div>
        <div class="admin-empty-state">
          <strong>当前单 APK 表单不适用于 PC 资源</strong>
          <span>PC package、patch、voice、file manifest 与 chunk manifest 具有不同身份结构，当前不提供手工新增或编辑。</span>
          <span>请使用已接入的官方采集与探活流程维护记录；左侧版本列表仍可用于只读浏览。</span>
        </div>
      </div>
    </AdminVersionList>
  </section>
</template>
