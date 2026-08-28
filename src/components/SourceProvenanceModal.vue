<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch, nextTick } from "vue";
import { gameIcons } from "../game-icons";

interface GameProvenance {
  id: string;
  name: string;
  subName: string;
  vendor: string;
  vendorCategory: "mihoyo" | "kuro" | "hypergryph" | "perfectworld";
  apkSource: {
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
      description: "官方动态接口轮询与直链提取，支持历史版本自动归档",
      endpointName: "api-takumi.mihoyo.com/.../ys_cn/official/android_default",
    },
    pcSource: {
      channel: "HoyoFiles / Amarea 版本库",
      description: "完整包、补丁路线及资源分块 (Chunks) 清单聚合",
      upstreamProject: "hoyo-files.amarea.cn",
      upstreamUrl: "https://hoyo-files.amarea.cn/",
    },
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
      description: "官方动态接口轮询与直链提取，支持历史版本自动归档",
      endpointName: "api-takumi.mihoyo.com/.../hkrpg_cn/official/android_default",
    },
    pcSource: {
      channel: "HoyoFiles / Amarea 版本库",
      description: "完整包、补丁路线及资源分块 (Chunks) 清单聚合",
      upstreamProject: "hoyo-files.amarea.cn",
      upstreamUrl: "https://hoyo-files.amarea.cn/",
    },
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
      description: "官方动态接口轮询与直链提取，支持历史版本自动归档",
      endpointName: "api-takumi.mihoyo.com/.../nap_cn/official/android_default",
    },
    pcSource: {
      channel: "HoyoFiles / Amarea 版本库",
      description: "完整包、补丁路线及资源分块 (Chunks) 清单聚合",
      upstreamProject: "hoyo-files.amarea.cn",
      upstreamUrl: "https://hoyo-files.amarea.cn/",
    },
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
      description: "官方动态接口轮询与直链提取，支持历史版本自动归档",
      endpointName: "api-takumi.mihoyo.com/.../bh3_cn/bh3/android_official",
    },
    pcSource: {
      channel: "HoyoFiles / Amarea + 历史快照",
      description: "PC 完整包、补丁清单及人工校准历史记录",
      upstreamProject: "hoyo-files.amarea.cn",
      upstreamUrl: "https://hoyo-files.amarea.cn/",
    },
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
    officialHosts: ["benghuai.com"],
  },
  {
    id: "wuwa",
    name: "鸣潮",
    subName: "Wuthering Waves",
    vendor: "库洛游戏 (Kuro Games)",
    vendorCategory: "kuro",
    apkSource: {
      channel: "库洛官方应用清单",
      description: "官方多语言渠道与版本 Manifest 解析，沉淀完整历史序列",
      endpointName: "download.kurogames.com/mc_.../official/cn/zh-Hans/android_app.json",
    },
    pcSource: {
      channel: "社区开源抓包与快照恢复",
      description: "启动器 index 动态解析、Wayback 快照与预下载 CDN 目录捕获",
      upstreamProject: "yuhkix/wuwa-downloader",
      upstreamUrl: "https://github.com/yuhkix/wuwa-downloader",
    },
    officialHosts: ["mirrors-package-mc.aki-game.com", "pcdownload-*.aki-game.com"],
  },
  {
    id: "pns",
    name: "战双帕弥什",
    subName: "Punishing: Gray Raven",
    vendor: "库洛游戏 (Kuro Games)",
    vendorCategory: "kuro",
    apkSource: {
      channel: "库洛官方应用清单",
      description: "官方多语言渠道与版本 Manifest 解析，沉淀完整历史序列",
      endpointName: "download.kurogames.com/pns/official/cn/zh-Hans/androidpc_app.json",
    },
    officialHosts: ["package.kurogames.com"],
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
      channel: "明日方舟 PC 官方网站与启动器",
      description: "官方 Launcher API 直出 PC 完整安装包分卷清单",
      upstreamProject: "明日方舟 PC 官方网站",
      upstreamUrl: "https://ak.hypergryph.com/pcs",
    },
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
      description: "官方 Launcher 接口轮询，抓取测试服安装包",
      endpointName: "launcher.hypergryph.com/game/latest/6LL0KJuqHBVz33WK/1/1",
    },
    pcSource: {
      channel: "第三方 API 历史归档与镜像",
      description: "鹰角启动器数据归档、版本补丁路线及 main/initial 资源索引",
      upstreamProject: "ak-endfield-api-archive",
      upstreamUrl: "https://ak-endfield-api-archive.daydreamer-json.cc/",
    },
    officialHosts: ["beyond.hycdn.cn", "github.com/AetherArchive"],
  },
  {
    id: "nte",
    name: "异环",
    subName: "Neverness to Everness",
    vendor: "完美世界 (Perfect World)",
    vendorCategory: "perfectworld",
    apkSource: {
      channel: "完美世界公共运维配置脚本",
      description: "官方公共数据通道解析与直链动态更新",
      endpointName: "static.games.wanmei.com/.../yh-gameDownload.js",
    },
    pcSource: {
      channel: "官方 PatcherSDK 协议",
      description: "读取官方 config.xml，自动解密 ResList.bin.zip 清单提取文件与补丁",
      upstreamProject: "完美世界官方发布 CDN",
      upstreamUrl: "https://yhcdn1.wmupd.com/",
    },
    officialHosts: ["yhcdn1.wmupd.com", "yhcdn2.wmupd.com"],
  },
  {
    id: "p5x",
    name: "女神异闻录：夜幕魅影",
    subName: "Persona 5: The Phantom X",
    vendor: "完美世界 (Perfect World)",
    vendorCategory: "perfectworld",
    apkSource: {
      channel: "完美世界公共运维配置脚本",
      description: "官方公共数据通道解析与直链动态更新",
      endpointName: "static.games.wanmei.com/.../p5x-gameDownload.js",
    },
    pcSource: {
      channel: "官方 PatcherSDK 协议",
      description: "读取官方 config.xml，自动解密 ResList.bin.zip 清单提取文件与补丁",
      upstreamProject: "完美世界官方发布 CDN",
      upstreamUrl: "https://nsywl-client-dev1.wmupd.com/",
    },
    officialHosts: ["nsywl-client-dev1.wmupd.com", "nsywl-client-dev2.wmupd.com"],
  },
  {
    id: "tof",
    name: "幻塔",
    subName: "Tower of Fantasy",
    vendor: "完美世界 (Perfect World)",
    vendorCategory: "perfectworld",
    apkSource: {
      channel: "完美世界公共运维配置脚本",
      description: "官方公共数据通道解析与直链动态更新",
      endpointName: "static.games.wanmei.com/.../ht-gameDownload.js",
    },
    pcSource: {
      channel: "官方 PatcherSDK 协议",
      description: "读取官方 config.xml，自动解密 ResList.bin.zip 清单提取文件与补丁",
      upstreamProject: "完美世界官方发布 CDN",
      upstreamUrl: "https://htcdn1.wmupd.com/",
    },
    officialHosts: ["htcdn1.wmupd.com", "htcdn2.wmupd.com"],
  },
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

watch(
  () => props.open,
  (isOpen) => {
    if (isOpen) {
      document.body.style.overflow = "hidden";
      nextTick(() => {
        if (props.activeGameId && activeCardRef.value) {
          activeCardRef.value.scrollIntoView({ behavior: "smooth", block: "nearest" });
        }
      });
    } else {
      document.body.style.overflow = "";
    }
  }
);

onMounted(() => {
  window.addEventListener("keydown", handleKeydown);
});

onUnmounted(() => {
  window.removeEventListener("keydown", handleKeydown);
  document.body.style.overflow = "";
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
              <h2 class="header-title">官方 CDN 与数据溯源说明</h2>
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
          <!-- 官方安全与直链申明 Bento -->
          <section class="provenance-bento-strip">
            <div class="bento-card">
              <div class="bento-icon">🔒</div>
              <div class="bento-meta">
                <strong>官方原厂直链</strong>
                <p>本站不托管任何游戏二进制包体，所有 URL 均直指各厂商官方一级 CDN，原汁原味绝无二传或篡改。</p>
              </div>
            </div>

            <div class="bento-card">
              <div class="bento-icon">🛡️</div>
              <div class="bento-meta">
                <strong>哈希完整性校验</strong>
                <p>所有入库资源均匹配厂商官方 ETag / MD5 / CRC64 校验签名，支持端侧严格对比。</p>
              </div>
            </div>

            <div class="bento-card">
              <div class="bento-icon">⚡</div>
              <div class="bento-meta">
                <strong>定期探活与可用性</strong>
                <p>后台定时通过 HTTP 206 Range 发起毫秒级可用性探活，剔除或标明失效链接。</p>
              </div>
            </div>
          </section>

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
                type="button"
                class="filter-tab"
                :class="{ active: selectedCategory === 'mihoyo' }"
                @click="selectedCategory = 'mihoyo'"
              >
                米哈游 (5)
              </button>
              <button
                type="button"
                class="filter-tab"
                :class="{ active: selectedCategory === 'kuro' }"
                @click="selectedCategory = 'kuro'"
              >
                库洛游戏 (2)
              </button>
              <button
                type="button"
                class="filter-tab"
                :class="{ active: selectedCategory === 'hypergryph' }"
                @click="selectedCategory = 'hypergryph'"
              >
                鹰角网络 (2)
              </button>
              <button
                type="button"
                class="filter-tab"
                :class="{ active: selectedCategory === 'perfectworld' }"
                @click="selectedCategory = 'perfectworld'"
              >
                完美世界 (3)
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
                <div class="provenance-row">
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
                    <span>PC 客户端与补丁</span>
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

                <!-- 官方 CDN 域名白名单 -->
                <div class="provenance-row">
                  <div class="row-label">
                    <span class="row-icon">🌐</span>
                    <span>官方 CDN 域名</span>
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
