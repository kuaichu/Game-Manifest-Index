<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch, nextTick } from "vue";
import { gameIcons } from "../game-icons";
import { useModalScrollLock } from "../composables/useModalScrollLock";

interface GameProvenance {
  id: string;
  name: string;
  subName: string;
  vendor: string;
  vendorCategory: "mihoyo" | "kuro" | "hypergryph" | "perfectworld" | "manjuu";
  apkSource?: {
    channel: string;
    description: string;
    endpointName: string;
  };
  pcSource?: {
    channel: string;
    description: string;
    upstreamProject?: string;
    upstreamUrl?: string;
  };
  historySource?: string;
  officialHosts: string[];
}

const props = defineProps<{
  open: boolean;
  activeGameId?: string;
  originPos?: { x: number; y: number } | null;
}>();

const emit = defineEmits<{
  (e: "close"): void;
}>();

const originStyle = computed(() => {
  if (props.originPos && typeof window !== "undefined") {
    const centerX = window.innerWidth / 2;
    const centerY = window.innerHeight / 2;
    const dx = Math.round(props.originPos.x - centerX);
    const dy = Math.round(props.originPos.y - centerY);
    return {
      "--origin-x": `${dx}px`,
      "--origin-y": `${dy}px`,
    };
  }
  return {
    "--origin-x": "38vw",
    "--origin-y": "-38vh",
  };
});

const selectedCategory = ref<string>("all");
const searchQuery = ref<string>("");
const activeCardRef = ref<HTMLElement | null>(null);

const GAME_PROVENANCE_LIST: GameProvenance[] = [
  {
    id: "hk4e",
    name: "原神",
    subName: "Genshin Impact",
    vendor: "米哈游 (miHoYo)",
    vendorCategory: "mihoyo",
    apkSource: {
      channel: "米哈游官方下载传送门 API",
      description: "从官方下载接口发现当前 Android 版本，提取安装包链接并持续归档。",
      endpointName: "api-takumi.mihoyo.com/.../ys_cn/official/android_default",
    },
    pcSource: {
      channel: "米哈游官方 HoYoPlay / Sophon 接口",
      description: "从 HoYoPlay 获取游戏与语音包、补丁，从 Sophon 获取资源分块清单。",
      upstreamProject: "官方包接口",
      upstreamUrl: "https://hyp-api.mihoyo.com/hyp/hyp-connect/api/getGamePackages?launcher_id=jGHBHlcOq1&game_ids[]=1Z8W5NHUQb",
    },
    historySource: "部分 PC 历史版本通过 HoyoFiles / Amarea 导入，保留第三方历史来源。",
    officialHosts: ["autopatchcn.yuanshen.com"],
  },
  {
    id: "hkrpg",
    name: "崩坏：星穹铁道",
    subName: "Honkai: Star Rail",
    vendor: "米哈游 (miHoYo)",
    vendorCategory: "mihoyo",
    apkSource: {
      channel: "米哈游官方下载传送门 API",
      description: "从官方下载接口发现当前 Android 版本，提取安装包链接并持续归档。",
      endpointName: "api-takumi.mihoyo.com/.../hkrpg_cn/official/android_default",
    },
    pcSource: {
      channel: "米哈游官方 HoYoPlay / Sophon 接口",
      description: "从 HoYoPlay 获取游戏与语音包、补丁，从 Sophon 获取资源分块清单。",
      upstreamProject: "官方包接口",
      upstreamUrl: "https://hyp-api.mihoyo.com/hyp/hyp-connect/api/getGamePackages?launcher_id=jGHBHlcOq1&game_ids[]=64kMb5iAWu",
    },
    historySource: "部分 PC 历史版本通过 HoyoFiles / Amarea 导入，保留第三方历史来源。",
    officialHosts: ["autopatchcn.bhsr.com"],
  },
  {
    id: "nap",
    name: "绝区零",
    subName: "Zenless Zone Zero",
    vendor: "米哈游 (miHoYo)",
    vendorCategory: "mihoyo",
    apkSource: {
      channel: "米哈游官方下载传送门 API",
      description: "从官方下载接口发现当前 Android 版本，提取安装包链接并持续归档。",
      endpointName: "api-takumi.mihoyo.com/.../nap_cn/official/android_default",
    },
    pcSource: {
      channel: "米哈游官方 HoYoPlay / Sophon 接口",
      description: "从 HoYoPlay 获取游戏与语音包、补丁，从 Sophon 获取资源分块清单。",
      upstreamProject: "官方包接口",
      upstreamUrl: "https://hyp-api.mihoyo.com/hyp/hyp-connect/api/getGamePackages?launcher_id=jGHBHlcOq1&game_ids[]=x6znKlJ0xK",
    },
    historySource: "部分 PC 历史版本通过 HoyoFiles / Amarea 导入，保留第三方历史来源。",
    officialHosts: ["autopatchcn.juequling.com"],
  },
  {
    id: "bh3",
    name: "崩坏3",
    subName: "Honkai Impact 3rd",
    vendor: "米哈游 (miHoYo)",
    vendorCategory: "mihoyo",
    apkSource: {
      channel: "米哈游官方下载传送门 API",
      description: "从官方下载接口发现当前 Android 版本，提取安装包链接并持续归档。",
      endpointName: "api-takumi.mihoyo.com/.../bh3_cn/bh3/android_official",
    },
    pcSource: {
      channel: "米哈游官方 HoYoPlay / Sophon 接口",
      description: "从 HoYoPlay 获取游戏与语音包、补丁，从 Sophon 获取资源分块清单。",
      upstreamProject: "官方包接口",
      upstreamUrl: "https://hyp-api.mihoyo.com/hyp/hyp-connect/api/getGamePackages?launcher_id=jGHBHlcOq1&game_ids[]=osvnlOc0S8",
    },
    historySource: "部分 PC 历史版本来自 HoyoFiles / Amarea 或旧项目迁移，保留原有来源。",
    officialHosts: ["bundle.bh3.com", "autopatchcn.bh3.com"],
  },
  {
    id: "bh2",
    name: "崩坏学园2",
    subName: "Houkai Gakuen 2",
    vendor: "米哈游 (miHoYo)",
    vendorCategory: "mihoyo",
    apkSource: {
      channel: "崩坏学园2 官方下载页",
      description: "官方官网动态重定向与下载链接实时抓取",
      endpointName: "benghuai.com/download/latest",
    },
    officialHosts: ["static.benghuai.com"],
  },
  {
    id: "wuwa",
    name: "鸣潮",
    subName: "Wuthering Waves",
    vendor: "库洛游戏 (Kuro Games)",
    vendorCategory: "kuro",
    apkSource: {
      channel: "库洛官方应用清单",
      description: "读取官方 Android 应用清单，发现当前版本并归档安装包链接。",
      endpointName: "download.kurogames.com/mc_.../official/cn/zh-Hans/android_app.json",
    },
    pcSource: {
      channel: "库洛官方 GameStarter 启动器清单",
      description: "读取官方启动器配置及资源清单，归档当前 PC 版本的文件和补丁信息。",
      upstreamProject: "官方启动器配置",
      upstreamUrl: "https://prod-cn-alicdn-gamestarter.kurogame.com/launcher/game/G152/10003_Y8xXrXk65DqFHEDgApn3cpK5lfczpFx5/index.json",
    },
    historySource: "PC 历史版本包含旧项目迁移记录，部分保留了官方历史清单地址；未记录的发现来源不作推断。",
    officialHosts: ["mirrors-package-mc.aki-game.com", "pcdownload-aliyun.aki-game.com", "pcdownload-qcloud.aki-game.com", "pcdownload-huoshan.aki-game.com"],
  },
  {
    id: "pns",
    name: "战双帕弥什",
    subName: "Punishing: Gray Raven",
    vendor: "库洛游戏 (Kuro Games)",
    vendorCategory: "kuro",
    apkSource: {
      channel: "库洛官方应用清单",
      description: "读取官方 Android 应用清单，发现当前版本并归档安装包链接。",
      endpointName: "download.kurogames.com/pns/official/cn/zh-Hans/androidpc_app.json",
    },
    officialHosts: ["zspms-txcdn-media.kurogame.com"],
  },
  {
    id: "arknights",
    name: "明日方舟",
    subName: "Arknights",
    vendor: "鹰角网络 (Hypergryph)",
    vendorCategory: "hypergryph",
    apkSource: {
      channel: "鹰角官方启动器 API",
      description: "官方 Launcher 接口轮询，抓取最新官服安装包",
      endpointName: "launcher.hypergryph.com/game/latest/GzD1CpaWgmSq1wew/1/1",
    },
    pcSource: {
      channel: "鹰角启动器官方 API",
      description: "最新 PC 完整包从官方 API 自动采集，包含分卷大小和 MD5。",
      upstreamProject: "鹰角启动器官方 API",
      upstreamUrl: "https://launcher.hypergryph.com/api/proxy/batch_proxy",
    },
    historySource: "部分 PC 历史版本来自旧项目迁移，保留原有来源。",
    officialHosts: ["ak.hycdn.cn"],
  },
  {
    id: "endfield",
    name: "明日方舟：终末地",
    subName: "Arknights: Endfield",
    vendor: "鹰角网络 (Hypergryph)",
    vendorCategory: "hypergryph",
    apkSource: {
      channel: "鹰角官方启动器 API",
      description: "从官方 Launcher 接口获取当前官服 Android 安装包链接。",
      endpointName: "launcher.hypergryph.com/game/latest/6LL0KJuqHBVz33WK/1/1",
    },
    pcSource: {
      channel: "鹰角启动器官方 API",
      description: "最新 PC 完整包从官方 API 自动采集，下载链接使用官方 OSS 地址。",
      upstreamProject: "鹰角启动器官方 API",
      upstreamUrl: "https://launcher.hypergryph.com/api/proxy/batch_proxy",
    },
    historySource: "历史版本包含旧项目迁移、Wayback 记录补录；部分资源保留标记为镜像的 GitHub 候选链接。",
    officialHosts: ["beyond.hycdn.cn", "beyond-prod.oss-cn-shanghai.aliyuncs.com"],
  },
  {
    id: "nte",
    name: "异环",
    subName: "Neverness to Everness",
    vendor: "完美世界 (Perfect World)",
    vendorCategory: "perfectworld",
    apkSource: {
      channel: "完美世界官方游戏下载配置",
      description: "解析官方 gameDownload.js 配置，提取当前 Android 安装包链接。",
      endpointName: "static.games.wanmei.com/.../yh-gameDownload.js",
    },
    pcSource: {
      channel: "完美世界官方 PatcherSDK",
      description: "读取官方 config.xml 并跟随版本分支，解码 ResList.bin.zip，提取文件与补丁条目。",
      upstreamProject: "官方版本配置",
      upstreamUrl: "https://yhcdn1.wmupd.com/clientRes/publish_PC/Version/Windows/config.xml",
    },
    historySource: "PC 历史版本包含旧项目迁移记录及从官方 ResList 清单人工补录的记录。",
    officialHosts: ["yhapk.wmupd.com", "yhcdn1.wmupd.com", "yhcdn2.wmupd.com"],
  },
  {
    id: "p5x",
    name: "女神异闻录：夜幕魅影",
    subName: "Persona 5: The Phantom X",
    vendor: "完美世界 (Perfect World)",
    vendorCategory: "perfectworld",
    apkSource: {
      channel: "完美世界官方游戏下载配置",
      description: "解析官方 gameDownload.js 配置，提取当前 Android 安装包链接。",
      endpointName: "static.games.wanmei.com/.../p5x-gameDownload.js",
    },
    pcSource: {
      channel: "完美世界官方 PatcherSDK",
      description: "读取官方 config.xml，解码 ResList.bin.zip，提取文件与补丁条目。",
      upstreamProject: "官方版本配置",
      upstreamUrl: "https://nsywl-client-dev1.wmupd.com/clientRes/CN_OB_OFFICIAL/Version/Windows/config.xml",
    },
    officialHosts: ["p5xapk.wmupd.com", "nsywl-client-dev1.wmupd.com", "nsywl-client-dev2.wmupd.com"],
  },
  {
    id: "tof",
    name: "幻塔",
    subName: "Tower of Fantasy",
    vendor: "完美世界 (Perfect World)",
    vendorCategory: "perfectworld",
    apkSource: {
      channel: "完美世界官方游戏下载配置",
      description: "解析官方 gameDownload.js 配置，提取当前 Android 安装包链接。",
      endpointName: "static.games.wanmei.com/.../ht-gameDownload.js",
    },
    pcSource: {
      channel: "完美世界官方 PatcherSDK",
      description: "读取官方 config.xml，解码 ResList.bin.zip，提取文件与补丁条目。",
      upstreamProject: "官方版本配置",
      upstreamUrl: "https://htcdn1.wmupd.com/clientRes/Windows55/Version/Windows/config.xml",
    },
    historySource: "部分 PC 历史版本来自旧项目迁移，保留原有 PatcherSDK 归档来源。",
    officialHosts: ["htapk.wmupd.com", "htcdn1.wmupd.com", "htcdn2.wmupd.com"],
  },
  {
    id: "abc",
    name: "崩坏：因缘精灵",
    subName: "Honkai: Nexus Anima",
    vendor: "米哈游 (miHoYo)",
    vendorCategory: "mihoyo",
    pcSource: {
      channel: "官方启动器日志与 Sophon 清单（人工归档）",
      description: "根据 HoYoPlay CBT2 启动器日志和官方 Sophon 清单整理内测资源；尚未接入自动采集。",
    },
    officialHosts: ["autopatchcn-beta.bhyyjl.com"],
  },
  {
    id: "azurpromilia",
    name: "蓝色星原：旅谣",
    subName: "Azur Promilia",
    vendor: "蛮啾网络 (Manjuu)",
    vendorCategory: "manjuu",
    apkSource: {
      channel: "蛮啾官方内测 APK（人工归档）",
      description: "保留官方内测安装包的既有归档，尚未接入自动采集。",
      endpointName: "syncstation.manjuu.com/azurpromilia/android/...",
    },
    pcSource: {
      channel: "蛮啾官方 PC 启动器接口（既有归档）",
      description: "既有内测记录来自官方 packageconfig 接口，尚未接入自动采集。",
      upstreamProject: "官方版本接口",
      upstreamUrl: "https://api-grp.manjuu.com/pc-launcher/client/gameversion/packageconfig",
    },
    officialHosts: ["syncstation.manjuu.com"],
  },
];

const VENDOR_FILTERS: { id: GameProvenance["vendorCategory"]; label: string }[] = [
  { id: "mihoyo", label: "米哈游" },
  { id: "kuro", label: "库洛游戏" },
  { id: "hypergryph", label: "鹰角网络" },
  { id: "perfectworld", label: "完美世界" },
  { id: "manjuu", label: "蛮啾网络" },
];

const filteredList = computed(() => {
  let list = GAME_PROVENANCE_LIST;
  if (selectedCategory.value !== "all") {
    list = list.filter((item) => item.vendorCategory === selectedCategory.value);
  }
  if (searchQuery.value.trim()) {
    const q = searchQuery.value.trim().toLowerCase();
    list = list.filter(
      (item) =>
        item.name.toLowerCase().includes(q) ||
        item.subName.toLowerCase().includes(q) ||
        item.id.toLowerCase().includes(q) ||
        item.vendor.toLowerCase().includes(q) ||
        item.officialHosts.some((h) => h.toLowerCase().includes(q))
    );
  }
  return list;
});

function handleKeydown(e: KeyboardEvent): void {
  if (e.key === "Escape" && props.open) {
    emit("close");
  }
}

useModalScrollLock(() => props.open);

watch(
  () => props.open,
  (isOpen) => {
    if (isOpen) {
      nextTick(() => {
        if (props.activeGameId && activeCardRef.value) {
          activeCardRef.value.scrollIntoView({ behavior: "smooth", block: "nearest" });
        }
      });
    }
  }
);

onMounted(() => {
  window.addEventListener("keydown", handleKeydown);
});

onUnmounted(() => {
  window.removeEventListener("keydown", handleKeydown);
});
</script>

<template>
  <teleport to="body">
    <transition name="modal-zoom">
      <div
        v-if="open"
        class="provenance-modal-backdrop"
        :style="originStyle"
        @click.self="emit('close')"
      >
        <div class="provenance-modal-dialog" role="dialog" aria-modal="true">
        <!-- 弹窗顶部栏 -->
        <header class="provenance-modal-header">
          <div class="header-left">
            <div class="header-icon-box">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <circle cx="12" cy="12" r="10" />
                <line x1="2" y1="12" x2="22" y2="12" />
                <path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z" />
              </svg>
            </div>
            <div>
              <div class="header-kicker">DATA SOURCES & PROVENANCE</div>
              <h2 class="header-title">数据来源与历史溯源说明</h2>
            </div>
          </div>
          <button class="modal-close-btn" type="button" aria-label="关闭" @click="emit('close')">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2">
              <line x1="18" y1="6" x2="6" y2="18" />
              <line x1="6" y1="6" x2="18" y2="18" />
            </svg>
          </button>
        </header>

        <!-- 弹窗可滚动主体 -->
        <div class="provenance-modal-body">
          <!-- 来源、校验与探活边界 -->
          <section class="provenance-bento-strip">
            <div class="bento-card">
              <div class="bento-icon">🔒</div>
              <div class="bento-meta">
                <strong>官方采集与历史归档</strong>
                <p>当前自动采集使用官方接口；历史导入可能包含第三方来源或镜像候选，以具体记录为准。本站不持久托管安装包，下载可能经后端代理。</p>
              </div>
            </div>

            <div class="bento-card">
              <div class="bento-icon">🛡️</div>
              <div class="bento-meta">
                <strong>校验信息与完整性</strong>
                <p>按资源展示已有的校验信息。内置文件下载与分块合成功能支持完整性校验；普通直链下载不保证由本站校验，归档收录也不代表包体已完成校验。</p>
              </div>
            </div>

            <div class="bento-card">
              <div class="bento-icon">⚡</div>
              <div class="bento-meta">
                <strong>定期探活与可用性</strong>
                <p>定时任务按配置运行，普通模式跳过有效期内已验证可用的链接。探活仅反映检测时状态；失效链接保留并标记，不会自动删除。</p>
              </div>
            </div>
          </section>

          <p class="channel-desc">以下为来源渠道概览。部分早期迁移记录的来源信息不完整，不能据当前采集渠道反推历史来源，也不保证可补齐全部历史版本。</p>

          <!-- 筛选与搜索工具栏 -->
          <div class="provenance-filter-bar">
            <div class="vendor-filter-tabs">
              <button
                type="button"
                class="filter-tab"
                :class="{ active: selectedCategory === 'all' }"
                @click="selectedCategory = 'all'"
              >
                全部 ({{ GAME_PROVENANCE_LIST.length }})
              </button>
              <button
                v-for="vendor in VENDOR_FILTERS"
                :key="vendor.id"
                type="button"
                class="filter-tab"
                :class="{ active: selectedCategory === vendor.id }"
                @click="selectedCategory = vendor.id"
              >
                {{ vendor.label }} ({{ GAME_PROVENANCE_LIST.filter((item) => item.vendorCategory === vendor.id).length }})
              </button>
            </div>

            <div class="provenance-search-wrap">
              <svg class="search-micro-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <circle cx="11" cy="11" r="8" />
                <line x1="21" y1="21" x2="16.65" y2="16.65" />
              </svg>
              <input
                v-model="searchQuery"
                type="search"
                class="provenance-search-input"
                placeholder="搜索游戏、代号或域名…"
              />
            </div>
          </div>

          <!-- 游戏来源卡片矩阵 -->
          <div class="provenance-cards-grid">
            <article
              v-for="item in filteredList"
              :key="item.id"
              :ref="item.id === activeGameId ? (el) => (activeCardRef = el as HTMLElement) : undefined"
              class="game-provenance-card"
              :class="{ 'is-active-game': item.id === activeGameId }"
            >
              <div class="card-head">
                <div class="game-avatar-box">
                  <img
                    v-if="gameIcons[item.id]"
                    :src="gameIcons[item.id]"
                    :alt="item.name"
                    :class="{ 'endfield-icon': item.id === 'endfield' }"
                    class="game-avatar-img"
                  />
                  <span v-else class="game-avatar-fallback">{{ item.id.slice(0, 1).toUpperCase() }}</span>
                </div>
                <div class="game-head-info">
                  <div class="title-row">
                    <strong class="game-cn-name">{{ item.name }}</strong>
                    <code class="game-id-tag">{{ item.id }}</code>
                    <span v-if="item.id === activeGameId" class="active-game-pill">当前浏览游戏</span>
                  </div>
                  <span class="game-sub-name">{{ item.subName }} · {{ item.vendor }}</span>
                </div>
              </div>

              <div class="card-content-blocks">
                <!-- 移动端 Android APK 来源 -->
                <div v-if="item.apkSource" class="provenance-row">
                  <div class="row-label">
                    <span class="row-icon">📱</span>
                    <span>Android 安装包</span>
                  </div>
                  <div class="row-body">
                    <div class="channel-title">{{ item.apkSource.channel }}</div>
                    <div class="channel-desc">{{ item.apkSource.description }}</div>
                    <code class="channel-endpoint">{{ item.apkSource.endpointName }}</code>
                  </div>
                </div>

                <!-- PC 客户端 / 补丁来源 -->
                <div v-if="item.pcSource" class="provenance-row">
                  <div class="row-label">
                    <span class="row-icon">💻</span>
                    <span>PC 资源</span>
                  </div>
                  <div class="row-body">
                    <div class="channel-title-row">
                      <span class="channel-title">{{ item.pcSource.channel }}</span>
                      <a
                        v-if="item.pcSource.upstreamUrl"
                        :href="item.pcSource.upstreamUrl"
                        target="_blank"
                        rel="noreferrer"
                        class="upstream-link-badge"
                        :title="`访问上游来源: ${item.pcSource.upstreamProject}`"
                      >
                        <span>{{ item.pcSource.upstreamProject }}</span>
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2">
                          <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" />
                          <polyline points="15 3 21 3 21 9" />
                          <line x1="10" y1="14" x2="21" y2="3" />
                        </svg>
                      </a>
                    </div>
                    <div class="channel-desc">{{ item.pcSource.description }}</div>
                  </div>
                </div>

                <div v-if="item.historySource" class="provenance-row">
                  <div class="row-label">
                    <span class="row-icon">📚</span>
                    <span>历史来源</span>
                  </div>
                  <div class="row-body">
                    <div class="channel-desc">{{ item.historySource }}</div>
                  </div>
                </div>

                <!-- 已核对的部分官方资源域名，不代表完整白名单 -->
                <div class="provenance-row">
                  <div class="row-label">
                    <span class="row-icon">🌐</span>
                    <span>部分官方资源域名</span>
                  </div>
                  <div class="row-body">
                    <div class="host-tags-row">
                      <span v-for="host in item.officialHosts" :key="host" class="host-tag">
                        {{ host }}
                      </span>
                    </div>
                  </div>
                </div>
              </div>
            </article>

            <div v-if="!filteredList.length" class="provenance-empty">
              <span>未找到与 “{{ searchQuery }}” 相关的游戏来源信息</span>
            </div>
          </div>
        </div>

        <!-- 弹窗底部栏 -->
        <footer class="provenance-modal-footer">
          <div class="footer-left">
            <span class="footer-repo-text">项目开源地址：</span>
            <a
              href="https://github.com/kuaichu/Game-Manifest-Index"
              target="_blank"
              rel="noreferrer"
              class="footer-repo-link"
            >
              github.com/kuaichu/Game-Manifest-Index ↗
            </a>
          </div>
          <button type="button" class="admin-btn primary small close-action-btn" @click="emit('close')">
            <span>关闭窗口</span>
          </button>
        </footer>
      </div>
    </div>
    </transition>
  </teleport>
</template>
