const icon = (path: string) => new URL(`./assets/icons/${path}`, import.meta.url).href;

// NTE: official 300px touch icon, https://nte.perfectworld.com/public/images/icon.png
// PNS: official APK application icon, res/mipmap-xxxhdpi/icon.png (192px).
// APK URL is published by https://download.kurogames.com/pns/official/cn/zh-Hans/android_app.json
// Arknights: official APK application icon, res/mipmap-xxxhdpi/app_icon.png (192px).
// APK URL is published by https://launcher.hypergryph.com/game/latest/GzD1CpaWgmSq1wew/1/1
export const gameIcons: Record<string, string> = {
  abc: icon("abc.jpg"), arknights: icon("arknights.png"),
  azurpromilia: icon("azurpromilia.jpg"), bh2: icon("bh2.jpg"),
  bh3: icon("bh3.png"), endfield: icon("endfield.svg"),
  hk4e: icon("hk4e.png"), hkrpg: icon("hkrpg.png"),
  nap: icon("nap.png"), nte: icon("nte.png"),
  p5x: icon("p5x.jpg"), pns: icon("pns.png"),
  tof: icon("tof.jpg"), wuwa: icon("wuwa.png"),
};
