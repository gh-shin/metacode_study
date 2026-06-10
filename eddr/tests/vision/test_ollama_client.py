from pathlib import Path

import pytest

from eddr.db.repository import PhotoRecord
from eddr.vision.ollama_client import OllamaVisionClient, needs_conversion
from eddr.vision.prompt import P3_HYBRID_V2_PROMPT_NAME


def test_caption_photo_sends_metadata_prompt_to_ollama(monkeypatch, tmp_path: Path):
    image = tmp_path / "image.jpg"
    image.write_bytes(b"image")
    photo = PhotoRecord(
        id="local:abc",
        source="local",
        source_uri="/Users/shingh/Pictures/raw/IMG_0001.jpg",
        image_path=str(image),
        latitude=33.450701,
        longitude=126.570667,
    )
    calls = []

    def fake_chat(model, messages, options):
        calls.append({"model": model, "messages": messages, "options": options})
        return {"message": {"content": "Caption: A beach at sunset.\nSearch keywords: beach"}}

    monkeypatch.setattr("eddr.vision.ollama_client.ollama.chat", fake_chat)

    client = OllamaVisionClient(caption_model="vision-model", prompt_name=P3_HYBRID_V2_PROMPT_NAME)
    caption = client.caption_photo(photo)

    assert caption.startswith("Caption: A beach")
    assert calls[0]["model"] == "vision-model"
    assert calls[0]["messages"][0]["images"] == [str(image)]
    assert "latitude: 33.450701" in calls[0]["messages"][0]["content"]
    assert "image_path:" in calls[0]["messages"][0]["content"]
    assert calls[0]["options"] == {"seed": 42}


def test_caption_photo_uses_remote_host_client_when_host_given(monkeypatch, tmp_path: Path):
    image = tmp_path / "image.jpg"
    image.write_bytes(b"image")
    photo = PhotoRecord(
        id="local:remote",
        source="local",
        source_uri=str(image),
        image_path=str(image),
    )
    constructed = {}
    chat_calls = []

    class FakeClient:
        def __init__(self, host=None):
            constructed["host"] = host

        def chat(self, model, messages, options):
            chat_calls.append({"model": model, "messages": messages, "options": options})
            return {"message": {"content": "Caption: a remote scene.\nSearch keywords: scene"}}

    monkeypatch.setattr("eddr.vision.ollama_client.ollama.Client", FakeClient)

    client = OllamaVisionClient(host="http://192.168.0.56:11434")
    caption = client.caption_photo(photo)

    assert constructed["host"] == "http://192.168.0.56:11434"
    assert chat_calls[0]["model"] == "gemma4:e2b"
    assert chat_calls[0]["messages"][0]["images"] == [str(image)]
    assert caption.startswith("Caption: a remote scene")


def test_caption_photo_rejects_caption_that_echoes_sensitive_metadata(monkeypatch, tmp_path: Path):
    image = tmp_path / "image.jpg"
    image.write_bytes(b"image")
    photo = PhotoRecord(
        id="local:abc",
        source="local",
        source_uri="/Users/shingh/Pictures/raw/IMG_0001.jpg",
        image_path=str(image),
        latitude=33.450701,
        longitude=126.570667,
    )

    def fake_chat(model, messages, options):
        return {"message": {"content": f"Caption: private path {photo.image_path}"}}

    monkeypatch.setattr("eddr.vision.ollama_client.ollama.chat", fake_chat)

    client = OllamaVisionClient(prompt_name=P3_HYBRID_V2_PROMPT_NAME)
    with pytest.raises(ValueError, match="sensitive metadata"):
        client.caption_photo(photo)


def test_needs_conversion_only_for_unsupported_formats():
    assert needs_conversion(Path("/x/a.heic")) is True
    assert needs_conversion(Path("/x/a.HEIC")) is True
    assert needs_conversion(Path("/x/a.tiff")) is True
    assert needs_conversion(Path("/x/a.jpg")) is False
    assert needs_conversion(Path("/x/a.JPEG")) is False
    assert needs_conversion(Path("/x/a.png")) is False


def test_caption_photo_converts_unsupported_format_via_sips(monkeypatch, tmp_path: Path):
    image = tmp_path / "photo.heic"
    image.write_bytes(b"heic-bytes")
    photo = PhotoRecord(
        id="local:heic",
        source="local",
        source_uri=str(image),
        image_path=str(image),
    )

    sips_calls = []

    def fake_run(cmd, **kwargs):
        sips_calls.append(cmd)
        out_path = cmd[cmd.index("--out") + 1]
        Path(out_path).write_bytes(b"jpeg-bytes")

        class _Result:
            returncode = 0

        return _Result()

    monkeypatch.setattr("eddr.vision.ollama_client.subprocess.run", fake_run)

    chat_images = []

    def fake_chat(model, messages, options):
        sent = messages[0]["images"][0]
        chat_images.append(sent)
        assert Path(sent).exists()  # temp must exist when ollama reads it
        return {"message": {"content": "Caption: a converted scene.\nSearch keywords: scene"}}

    monkeypatch.setattr("eddr.vision.ollama_client.ollama.chat", fake_chat)

    caption = OllamaVisionClient().caption_photo(photo)

    assert caption.startswith("Caption: a converted scene")
    assert sips_calls and sips_calls[0][0] == "sips"
    sent = chat_images[0]
    assert sent.endswith(".jpg")
    assert sent != str(image)  # converted JPEG, not the original HEIC
    assert not Path(sent).exists()  # temp cleaned up afterwards
