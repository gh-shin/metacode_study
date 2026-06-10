"""모듈 경계에서 쓰는 경량 타입 별칭.

중첩된 ``list[list[float]]``·``dict[str, Any]`` 노출을 줄여 함수 시그니처의
가독성을 높인다. 의미만 부여하는 별칭이며 런타임 표현은 동일하다(예: 벡터
스토어는 값을 ChromaDB 계약 그대로 통과시킨다).
"""

from typing import Any

Embedding = list[float]
Metadata = dict[str, Any]
MetadataFilter = dict[str, Any]
