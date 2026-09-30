const icon = (path: string) => new URL(`./assets/icons/${path}`, import.meta.url).href;

export const gameIcons: Record<string, string> = {
  abc: icon("abc.jpg"), azurpromilia: icon("azurpromilia.jpg"),
  aethergazer: icon("aethergazer.ico"), arknights: icon("arknights.ico"),
  bh2: icon("bh2.jpg"),
  bh3: icon("bh3.png"), bluearchive: icon("bluearchive.png"), calabiyau: icon("calabiyau.png"),
  endfield: icon("endfield.svg"), gf2: icon("gf2.png"), hk4e: icon("hk4e.png"),
  hkrpg: icon("hkrpg.png"), nap: icon("nap.png"), nte: icon("nte.ico"),
  p5x: icon("p5x.jpg"), pns: icon("pns.png"), reverse1999: icon("reverse1999.png"),
  snowbreak: icon("snowbreak.svg"), tof: icon("tof.jpg"), wuwa: icon("wuwa.png"),
};
