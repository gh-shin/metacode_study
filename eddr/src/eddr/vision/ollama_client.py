"""Ollama API 통신 클라이언트 — 캡션 생성(chat)과 텍스트 임베딩(embed)을 제공한다."""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path
from typing import NamedTuple

import ollama

from eddr.constants import CAPTION_MODEL as _CAPTION_MODEL
from eddr.constants import EMBEDDING_MODEL as _EMBEDDING_MODEL
from eddr.db.repository import PhotoRecord
from eddr.types import Embedding
from eddr.vision.prompt import (
    P3_HYBRID_PROMPT_NAME,
    build_prompt_for_photo,
    ensure_caption_has_no_sensitive_metadata,
)

_OLLAMA_SUPPORTED_SUFFIXES = {".jpg", ".jpeg", ".png"}


def needs_conversion(image_path: Path) -> bool:
    """Ollama가 직접 읽을 수 없는 포맷(HEIC·TIFF·RAW 등)이면 True를 반환한다.

    Args:
        image_path: 검사할 이미지 경로.

    Returns:
        확장자가 ``_OLLAMA_SUPPORTED_SUFFIXES``에 없으면 True.
    """
    return image_path.suffix.lower() not in _OLLAMA_SUPPORTED_SUFFIXES


class OllamaImage(NamedTuple):
    """Ollama로 전송할 이미지 경로와 임시파일 여부.

    Attributes:
        path: 실제로 전송할 이미지 경로.
        is_temp: 변환으로 만든 임시 JPEG이면 True(호출자가 unlink 책임).
    """

    path: Path
    is_temp: bool


def to_ollama_image(image_path: Path) -> OllamaImage:
    """Ollama가 디코딩할 수 있는 이미지 경로를 돌려준다.

    HEIC·TIFF·RAW 등 Ollama가 못 읽는 포맷은 macOS ``sips``로 임시 JPEG으로 변환한다.

    Args:
        image_path: 원본 이미지 경로.

    Returns:
        전송 경로와 임시파일 여부를 담은 ``OllamaImage``. ``is_temp``가 True면
        호출자가 사용 후 임시파일을 unlink해야 한다.
    """
    if not needs_conversion(image_path):
        return OllamaImage(image_path, False)
    fd, tmp = tempfile.mkstemp(suffix=".jpg", prefix="eddr_vis_")
    os.close(fd)
    subprocess.run(
        ["sips", "-s", "format", "jpeg", str(image_path), "--out", tmp],
        check=True,
        capture_output=True,
    )
    return OllamaImage(Path(tmp), True)


class OllamaVisionClient:
    """Ollama 서버와 통신해 사진 캡션 생성 및 텍스트 임베딩을 수행하는 클라이언트."""

    def __init__(
        self,
        caption_model: str = _CAPTION_MODEL,
        embedding_model: str = _EMBEDDING_MODEL,
        prompt: str | None = None,
        prompt_name: str = P3_HYBRID_PROMPT_NAME,
        host: str | None = None,
        request_timeout: float = 600.0,
    ):
        """클라이언트를 초기화한다.

        Args:
            caption_model: 캡션 생성에 사용할 Ollama 모델 이름.
            embedding_model: 임베딩 생성에 사용할 Ollama 모델 이름.
            prompt: 고정 프롬프트 문자열. 설정 시 ``prompt_name``보다 우선한다(단,
                ``caption_photo``에서 ``prompt_name``을 명시적으로 전달하면 무시).
            prompt_name: 사용할 프롬프트 이름(``prompt``가 None일 때 사용).
            host: Ollama 서버 URL. None이면 기본 로컬 호스트를 사용한다.
            request_timeout: ollama HTTP 요청 제한 시간(초). 기본 600초 — 정상 캡션
                생성(30-60초)은 통과하고 무한 hang만 차단한다.
        """
        self.caption_model = caption_model
        self.embedding_model = embedding_model
        self.prompt = prompt
        self.prompt_name = prompt_name
        self.host = host
        # host=None이어도 모듈 레벨 ollama.chat/embed(timeout=None 싱글턴)를 쓰지
        # 않고 Client 인스턴스를 생성해 timeout을 일관 적용한다.
        self._client = ollama.Client(host=host, timeout=request_timeout)

    def caption_image(self, image_path: Path) -> str:
        """파일 경로로 직접 캡션을 생성한다(PhotoRecord 없이 호출하는 편의 메서드).

        Args:
            image_path: 캡션을 생성할 이미지 파일 경로.

        Returns:
            생성된 캡션 문자열.
        """
        photo = PhotoRecord(
            id=f"path:{image_path}",
            source="path",
            source_uri=str(image_path),
            image_path=str(image_path),
        )
        return self.caption_photo(photo)

    def caption_photo(self, photo: PhotoRecord, prompt_name: str | None = None) -> str:
        """PhotoRecord에 대응하는 이미지 파일로 캡션을 생성하고 민감정보 누출을 검사한다.

        필요 시 이미지를 임시 JPEG으로 변환한 뒤 Ollama chat API를 호출한다.
        캡션에 민감 메타데이터(경로·좌표 등)가 포함되면 ``ValueError``를 발생시킨다.

        Args:
            photo: 캡션을 생성할 사진 레코드.
            prompt_name: 사용할 프롬프트 이름. None이면 인스턴스 기본값을 따른다.

        Returns:
            생성된 캡션 문자열(앞뒤 공백 제거).

        Raises:
            ValueError: 캡션에 민감 메타데이터가 포함된 경우.
            subprocess.CalledProcessError: 이미지 변환(sips) 실패 시.
        """
        image_path = Path(photo.image_path or "")
        prompt = self._prompt_for_photo(photo, prompt_name)
        send_path, is_temp = to_ollama_image(image_path)
        try:
            response = self._chat(
                model=self.caption_model,
                messages=[
                    {
                        "role": "user",
                        "content": prompt,
                        "images": [str(send_path)],
                    }
                ],
                options={"seed": 42},
            )
        finally:
            if is_temp:
                send_path.unlink(missing_ok=True)
        caption = response["message"]["content"].strip()
        ensure_caption_has_no_sensitive_metadata(caption, photo)
        return caption

    def embed_texts(self, texts: list[str]) -> list[Embedding]:
        """텍스트 목록을 임베딩 벡터 목록으로 변환한다.

        Args:
            texts: 임베딩할 텍스트 문자열 목록.

        Returns:
            각 텍스트에 대응하는 float 리스트(임베딩 벡터)의 목록.
        """
        response = self._embed(model=self.embedding_model, input=texts)
        return [list(vec) for vec in response.embeddings]

    def _chat(self, **kwargs):
        return self._client.chat(**kwargs)

    def _embed(self, **kwargs):
        return self._client.embed(**kwargs)

    def _prompt_for_photo(self, photo: PhotoRecord, prompt_name: str | None) -> str:
        """고정 프롬프트 우선순위를 적용해 최종 프롬프트 문자열을 반환한다."""
        if self.prompt is not None and prompt_name is None:
            return self.prompt
        return build_prompt_for_photo(photo, prompt_name or self.prompt_name)
