const icon = (path: string) => new URL(`./assets/icons/${path}`, import.meta.url).href;

// NTE: official 300px touch icon, https://nte.perfectworld.com/public/images/icon.png
// PNS: official APK application icon, res/mipmap-xxxhdpi/icon.png (192px).
// APK URL is published by https://download.kurogames.com/pns/official/cn/zh-Hans/android_app.json
// Arknights: official APK application icon, res/mipmap-xxxhdpi/app_icon.png (192px).
// APK URL is published by https://launcher.hypergryph.com/game/latest/GzD1CpaWgmSq1wew/1/1
export const gameIcons: Record<string, string> = {
  abc: icon("abc.jpg"), azurpromilia: icon("azurpromilia.jpg"),
  aethergazer: icon("aethergazer.ico"), arknights: icon("arknights.png"),
  bh2: icon("bh2.jpg"),
  bh3: icon("bh3.png"), bluearchive: icon("bluearchive.png"), calabiyau: icon("calabiyau.png"),
  endfield: icon("endfield.svg"), gf2: icon("gf2.png"), hk4e: icon("hk4e.png"),
  hkrpg: icon("hkrpg.png"), nap: icon("nap.png"), nte: icon("nte.png"),
  p5x: icon("p5x.jpg"), pns: icon("pns.png"), reverse1999: icon("reverse1999.png"),
  snowbreak: icon("snowbreak.svg"), tof: icon("tof.jpg"), wuwa: icon("wuwa.png"),
};
