import { createRouter, createWebHistory } from "vue-router";
import AdminView from "./views/AdminView.vue";
import ArchiveView from "./views/ArchiveView.vue";
import NotFoundView from "./views/NotFoundView.vue";

const VIEW_STORAGE_KEY = "game-manifest-index-web-view-v1";

function savedArchivePath(): string {
  try {
    const path = localStorage.getItem(VIEW_STORAGE_KEY) || "";
    return path.startsWith("/games/") ? path : "/games/nte";
  } catch {
    return "/games/nte";
  }
}

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: "/", redirect: savedArchivePath },
    {
      path: "/android/:gameId?",
      redirect: (to) => {
        const gameId = String(to.params.gameId || "nte");
        return `/games/${encodeURIComponent(gameId)}/${encodeURIComponent(`${gameId}-android`)}`;
      },
    },
    { path: "/games/:gameId/:domainId?/:version?/:mode?", name: "archive", component: ArchiveView },
    { path: "/admin", name: "admin", component: AdminView },
    { path: "/:pathMatch(.*)*", name: "not-found", component: NotFoundView },
  ],
});
