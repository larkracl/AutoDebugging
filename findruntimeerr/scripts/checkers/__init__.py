"""
Checkers 패키지 초기화 파일.
이 파일은 각 체커 모듈에서 클래스들을 가져와서
외부(core.py 등)에서 쉽게 사용할 수 있도록 목록을 만들어 제공합니다.
"""

# 1. Base 클래스들 import
from checkers.base_checkers import BaseParsoChecker, BaseAstroidChecker

# 2. 실시간 Parso 체커들 import
from checkers.rt_checkers.name_error_checker import RTNameErrorParsoChecker
from checkers.rt_checkers.zero_division_checker import RTZeroDivisionParsoChecker

# 3. 상세 Astroid 체커들 import
from checkers.static_checkers.name_error_checker import StaticNameErrorChecker
from checkers.static_checkers.type_error_checker import StaticTypeErrorChecker
from checkers.static_checkers.attribute_error_checker import StaticAttributeErrorChecker
from checkers.static_checkers.index_error_checker import StaticIndexErrorChecker
from checkers.static_checkers.key_error_checker import StaticKeyErrorChecker
from checkers.static_checkers.infinite_loop_checker import StaticInfiniteLoopChecker
from checkers.static_checkers.recursion_checker import StaticRecursionChecker
from checkers.static_checkers.file_not_found_checker import StaticFileNotFoundChecker

# 4. 외부에서 사용할 체커 목록 정의
RT_CHECKERS_CLASSES = [
    RTNameErrorParsoChecker,
    RTZeroDivisionParsoChecker,
]

STATIC_CHECKERS_CLASSES = [
    StaticNameErrorChecker,
    StaticTypeErrorChecker,
    StaticAttributeErrorChecker,
    StaticIndexErrorChecker,
    StaticKeyErrorChecker,
    StaticInfiniteLoopChecker,
    # StaticRecursionChecker는 Linter.analyze_astroid 에서 별도 처리되므로 목록에 넣지 않음
    StaticFileNotFoundChecker,
]

__all__ = [
    'BaseParsoChecker', 'BaseAstroidChecker',
    'RTNameErrorParsoChecker', 'RTZeroDivisionParsoChecker',
    'StaticNameErrorChecker', 'StaticTypeErrorChecker', 'StaticAttributeErrorChecker',
    'StaticIndexErrorChecker', 'StaticKeyErrorChecker', 'StaticInfiniteLoopChecker',
    'StaticRecursionChecker', 'StaticFileNotFoundChecker',
    'RT_CHECKERS_CLASSES', 'STATIC_CHECKERS_CLASSES'
]
