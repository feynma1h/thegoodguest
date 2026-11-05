"""Spend ceiling, the Claude caller's rules, the privacy gate, the workspace."""
import json
import logging
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from PIL import Image as PILImage

from claude_layer import constants as C
from claude_layer import images
from claude_layer.client import (AnthropicClient, ClaudeCaller, ClaudeRefused, ClaudeUnusable, FakeClient, Image,
                                 PrivacyViolation, Request)
from claude_layer.scene_port import GcsScenePort, LocalScenePort
from claude_layer.spend import SpendCeilingReached, SpendLedger, Usage, cost_usd
from claude_layer.workspace import Workspace


def port(tmp_path):
    src = tmp_path / "src"
    (src / "captures" / "frames").mkdir(parents=True, exist_ok=True)
    (src / "captures" / "bundle.pb").write_bytes(b"x")
    (src / "captures" / "frames" / "000001.jpg").write_bytes(b"jpg")
    (src / "shell.json").write_text("{}")
    return LocalScenePort("s1", src, tmp_path / "out")


def req(stage="spec", content=None, model="claude-opus-5-5", max_tokens=1000):
    return Request(stage, model, "system", content or ["hello"], {"type": "object"}, max_tokens, box_id="b0")


def test_cost_uses_the_reported_usage_and_prices_unknown_models_dearest():
    assert cost_usd("claude-opus-5-5", Usage(input_tokens=1_000_000, output_tokens=1_000_000)) == pytest.approx(24.0)
    assert cost_usd("mystery", Usage(output_tokens=1_000_000)) == pytest.approx(20.0)


def test_ceiling_is_checked_before_the_call_and_sums_every_worker(tmp_path):
    p = port(tmp_path)
    a, b = SpendLedger(p, "a", 1.0), SpendLedger(p, "b", 1.0)
    a.record("claude-opus-5-5", Usage(input_tokens=100_000, output_tokens=20_000), "x")  # $0.80
    with pytest.raises(SpendCeilingReached):
        b.check("claude-opus-5-5", 20_000, 10_000)  # worst case $0.28 on top of $0.80
    b.check("claude-opus-5-5", 1_000, 1_000)
    fake = FakeClient([{"ok": 1}])
    caller = ClaudeCaller(fake, SpendLedger(p, "c", 0.5))
    with pytest.raises(SpendCeilingReached):
        caller.ask(req(max_tokens=8000), dict)
    assert fake.shapes == []  # refused before anything was sent


def test_ledger_survives_a_retried_task(tmp_path):
    p = port(tmp_path)
    SpendLedger(p, "w", 5).record("claude-opus-5-5", Usage(input_tokens=1000), "x")
    assert SpendLedger(p, "w", 5).own_usd() > 0


def test_invalid_answer_is_re_asked_once_with_the_error_then_given_up(tmp_path):
    fake = FakeClient([{"bad": 1}, {"bad": 2}])
    caller = ClaudeCaller(fake, SpendLedger(port(tmp_path), "w"))

    def validate(d):
        raise ValueError("nope")

    with pytest.raises(ClaudeUnusable):
        caller.ask(req(), validate)
    assert len(fake.shapes) == 2 and fake.shapes[0]["text_hash"] != fake.shapes[1]["text_hash"]
    fake = FakeClient([{"bad": 1}, {"good": 1}])
    out = ClaudeCaller(fake, SpendLedger(port(tmp_path), "w2")).ask(req(), lambda d: d if "good" in d else (_ for _ in ()).throw(ValueError("x")))
    assert out == {"good": 1}


def test_refusal_is_not_retried(tmp_path):
    fake = FakeClient([ClaudeRefused("r"), {"ok": 1}])
    with pytest.raises(ClaudeRefused):
        ClaudeCaller(fake, SpendLedger(port(tmp_path), "w")).ask(req(), dict)
    assert len(fake.shapes) == 1


def test_privacy_rules_on_images(tmp_path):
    caller = ClaudeCaller(FakeClient(lambda r: {}), SpendLedger(port(tmp_path), "w"))
    raw = Image("photo", b"p", 100, 100, masked=False)
    with pytest.raises(PrivacyViolation):
        caller.ask(req(content=[raw]), dict)
    big = Image("photo", b"p", 900, 100, masked=True)
    with pytest.raises(PrivacyViolation):
        caller.ask(req(content=[big]), dict)
    seven = [Image("photo", b"p", 100, 100, masked=True)] * 7
    with pytest.raises(PrivacyViolation):
        caller.ask(req(content=seven), dict)
    six = [Image("photo", b"p", 100, 100, masked=True)] * 6
    caller.ask(req(content=six), dict)
    with pytest.raises(PrivacyViolation):  # the finish pass never carries a photo
        caller.ask(req("finish", content=[Image("photo", b"p", 100, 100, masked=True)]), dict)


def test_call_log_has_sizes_and_no_pixels(tmp_path, caplog):
    caller = ClaudeCaller(FakeClient(lambda r: {}), SpendLedger(port(tmp_path), "w"))
    secret = b"PIXELBYTES-DO-NOT-LOG"
    with caplog.at_level(logging.INFO, logger="scene_finish.claude"):
        caller.ask(req(content=["a private prompt", Image("render", secret, 10, 10)]), dict)
    text = "\n".join(r.getMessage() for r in caplog.records)
    assert "claude_call" in text and "PIXELBYTES" not in text and "private prompt" not in text
    assert json.loads(text)["images"]["render"] == 1


def test_anthropic_client_request_shape_and_refusal():
    seen = {}

    class Msgs:
        def create(self, **kw):
            seen.update(kw)
            return SimpleNamespace(stop_reason="end_turn", content=[SimpleNamespace(type="text", text='{"a": 1}')],
                                   usage=SimpleNamespace(input_tokens=10, output_tokens=5, cache_read_input_tokens=3,
                                                         cache_creation_input_tokens=0), _request_id="req_1")

    c = AnthropicClient(SimpleNamespace(messages=Msgs()))
    r = c.create(req(content=["t", Image("render", b"png", 4, 4, "label")]))
    assert r.data == {"a": 1} and r.request_id == "req_1" and r.usage.cache_read_tokens == 3
    assert "thinking" not in seen and "tool_choice" not in seen
    assert seen["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert seen["output_config"]["format"]["type"] == "json_schema"

    class Refusing(Msgs):
        def create(self, **kw):
            return SimpleNamespace(stop_reason="refusal", content=[], usage=None)

    with pytest.raises(ClaudeRefused):
        AnthropicClient(SimpleNamespace(messages=Refusing())).create(req())


def _photo(w=800, h=600, colour=(120, 140, 160)):
    return PILImage.new("RGB", (w, h), colour)


def test_photo_crop_blacks_out_people_caps_size_and_fails_closed():
    person = np.zeros((600, 800), bool)
    person[100:300, 100:300] = True
    img = images.photo_crop(_photo(), (50, 50, 450, 450), 0, person, "crop")
    assert img.masked and max(img.width, img.height) <= C.PHOTO_CROP_MAX_SIDE_PX
    px = np.asarray(PILImage.open(__import__("io").BytesIO(img.png)))
    assert (px == 0).all(-1).any() and not (px == 0).all(-1).all()
    assert images.photo_crop(_photo(), (50, 50, 450, 450), 0, None) is None  # unknown mask: unusable
    mostly = np.ones((600, 800), bool)
    assert images.photo_crop(_photo(), (50, 50, 450, 450), 0, mostly) is None
    big = images.photo_crop(_photo(3000, 2000), (0, 0, 3000, 2000), 0, np.zeros((2000, 3000), bool))
    assert max(big.width, big.height) == C.PHOTO_CROP_MAX_SIDE_PX


def test_workspace_deletes_pixels_on_success_and_on_error_but_not_the_source(tmp_path):
    p = port(tmp_path)
    with Workspace(p) as root:
        (root / "crop.png").write_bytes(b"pixels")
        kept = root
        assert (root / "captures" / "frames" / "000001.jpg").is_file()
    assert not kept.exists() and (tmp_path / "src" / "captures" / "frames" / "000001.jpg").is_file()
    with pytest.raises(RuntimeError):
        with Workspace(p) as root:
            kept = root
            raise RuntimeError("boom")
    assert not kept.exists() and (tmp_path / "src" / "captures" / "bundle.pb").is_file()


def test_workspace_person_mask_fails_closed_unless_told_otherwise(tmp_path):
    p = port(tmp_path)
    ws = Workspace(p)
    assert ws.person_mask(1) is None
    np.savez(ws.root / "masks.tmp.npz", suppressed=np.ones((4, 4), bool))
    (ws.root / "masks").mkdir()
    (ws.root / "masks.tmp.npz").rename(ws.root / "masks" / "0001.npz")
    assert ws.person_mask(1).all()
    ws.close()
    ws2 = Workspace(p, assume_no_people=True)
    assert ws2.person_mask(7).shape == (1, 1)
    ws2.close()


def test_local_port_writes_beside_not_into_the_source_and_canonically(tmp_path):
    p = port(tmp_path)
    p.write_json("work/furniture/b.json", {"b": 1, "a": 2})
    assert (tmp_path / "out" / "work" / "furniture" / "b.json").read_text().index('"a"') < 30
    assert not (tmp_path / "src" / "work").exists()
    assert p.list_json("work/furniture/") == ["work/furniture/b.json"] and p.read_json("shell.json") == {}


def test_gcs_port_round_trip_and_materialises_an_even_spread_of_frames_and_masks(tmp_path, monkeypatch):
    import scenes

    class Blob:
        def __init__(self, store, name): self.store, self.name = store, name
        def exists(self): return self.name in self.store
        def download_as_bytes(self): return self.store[self.name]
        def upload_from_string(self, data, content_type=None): self.store[self.name] = data
        def download_to_filename(self, f): Path(f).write_bytes(self.store[self.name])

    class Client:
        def list_blobs(self, bucket, prefix=""): return [Blob(bucket.store, n) for n in sorted(bucket.store) if n.startswith(prefix)]

    class Bucket:
        def __init__(self): self.store, self.client = {}, Client()
        def blob(self, name): return Blob(self.store, name)

    class Storage:
        def __init__(self, buckets): self.buckets = buckets
        def bucket(self, name): return self.buckets[name]

    src = scenes.build(tmp_path / "src", n_frames=6)
    out, cap = Bucket(), Bucket()
    cap.store["x/bundle.pb"] = (src / "captures" / "bundle.pb").read_bytes()
    for i in range(6):
        cap.store[f"x/frames/{i:06d}.jpg"] = (src / "captures" / "frames" / f"{i:06d}.jpg").read_bytes()
    np.savez(tmp_path / "m.npz", suppressed=np.ones((2, 2), bool))
    out.store["scenes/s1/frames/0002/masks.npz"] = (tmp_path / "m.npz").read_bytes()
    monkeypatch.setattr(C, "MATERIALISE_MAX_FRAMES", 3)
    p = GcsScenePort("s1", out, Storage({"cap": cap}), "gs://cap/x/bundle.pb")
    p.write_json("boxes.json", {"boxes": []})
    assert p.read_json("boxes.json") == {"boxes": []} and p.read_json("nope.json") is None
    assert p.list_json("") == ["boxes.json"]
    with Workspace(p) as root:
        assert (root / "captures" / "bundle.pb").is_file() and (root / "boxes.json").is_file()
        got = sorted(f.name for f in (root / "captures" / "frames").iterdir())
        assert got == ["000000.jpg", "000002.jpg", "000005.jpg"]
        assert [m.name for m in (root / "masks").iterdir()] == ["0002.npz"]
