import json
import unittest
from pathlib import Path

from probe_adapters.registry import ANDROID_ADAPTERS, adapter_for
from probe_adapters.common import ProbeError


EXPECTED = {
    ("android", "arknights"): "hypergryph_arknights_hycdn",
    ("android", "endfield"): "hypergryph_endfield_hycdn",
    ("android", "pns"): "kuro_pns_txcdn",
    ("android", "wuwa"): "kuro_wuwa_mc_cdn",
    ("android", "bh2"): "mihoyo_bh2_benghuai",
    ("android", "bh3"): "mihoyo_bh3_cdn",
    ("android", "hk4e"): "mihoyo_autopatch",
    ("android", "hkrpg"): "mihoyo_autopatch",
    ("android", "nap"): "mihoyo_autopatch",
    ("android", "nte"): "perfectworld_webops",
    ("android", "p5x"): "perfectworld_webops",
    ("android", "tof"): "perfectworld_webops",
    ("windows", "wuwa"): "kuro_cdn",
    ("windows", "bh3"): "mihoyo_bh3_cdn",
    ("windows", "hk4e"): "mihoyo_autopatch",
    ("windows", "hkrpg"): "mihoyo_autopatch",
    ("windows", "nap"): "mihoyo_autopatch",
    ("windows", "nte"): "perfectworld_patcher",
    ("windows", "p5x"): "perfectworld_patcher",
    ("windows", "tof"): "perfectworld_patcher",
}


class ProbeRegistryTests(unittest.TestCase):
    def test_internal_registry_has_eight_specialized_adapters(self):
        self.assertEqual(len(ANDROID_ADAPTERS), 8)
        self.assertEqual(len({adapter.NAME for adapter in ANDROID_ADAPTERS}), 8)

    def test_generic_requires_url_only_http_apk(self):
        self.assertEqual(adapter_for(None, None, "https://x.test/game.apk").NAME, "shared_generic_apk")
        for args in (("mihoyo", None, "https://x.test/game.apk"), (None, "x", "https://x.test/game.apk"),
                     (None, None, "ftp://x.test/game.apk"), (None, None, "https://x.test/game.zip")):
            with self.subTest(args=args), self.assertRaises(ProbeError):
                adapter_for(*args)
    def test_every_stored_url_has_one_vendor_type_adapter(self) -> None:
        root = Path(__file__).resolve().parents[1] / "data"
        count = 0
        for path in root.glob("*/*/*/*.json"):
            if path.name == "index.json":
                continue
            record = json.loads(path.read_text(encoding="utf-8"))
            for artifact in record["artifacts"]:
                for candidate in artifact["urls"]:
                    adapter = adapter_for(
                        record["vendor"], record["game_id"], candidate["url"],
                        platform=record["platform"],
                    )
                    self.assertEqual(
                        adapter.NAME,
                        EXPECTED[(record["platform"], record["game_id"])],
                        path,
                    )
                    count += 1
        self.assertEqual(count, 1848)

    def test_url_only_dispatch_still_uses_the_specific_adapter(self) -> None:
        adapter = adapter_for(
            None,
            None,
            "https://autopatchcn.yuanshen.com/client_app/download/Android/20260803155301_token/game.apk",
        )
        self.assertEqual(adapter.NAME, "mihoyo_autopatch")


if __name__ == "__main__":
    unittest.main()
