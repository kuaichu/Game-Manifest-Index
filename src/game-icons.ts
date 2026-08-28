const icon = (path: string) => new URL(`./assets/icons/${path}`, import.meta.url).href;

export const gameIcons: Record<string, string> = {
  aethergazer: icon("aethergazer.ico"), arknights: icon("arknights.ico"),
  bh2: "https://is1-ssl.mzstatic.com/image/thumb/Purple211/v4/ad/fb/68/adfb68b6-ae24-88d5-ebb1-6d925a0c1bf2/AppIcon-0-0-1x_U007emarketing-0-8-0-85-220.png/512x512bb.jpg",
  bh3: icon("bh3.png"), bluearchive: icon("bluearchive.png"), calabiyau: icon("calabiyau.png"),
  endfield: icon("endfield.svg"), gf2: icon("gf2.png"), hk4e: icon("hk4e.png"),
  hkrpg: icon("hkrpg.png"), nap: icon("nap.png"), nte: icon("nte.ico"),
  p5x: icon("p5x.jpg"), pns: icon("pns.png"), reverse1999: icon("reverse1999.png"),
  snowbreak: icon("snowbreak.svg"), tof: icon("tof.jpg"), wuwa: icon("wuwa.png"),
};
