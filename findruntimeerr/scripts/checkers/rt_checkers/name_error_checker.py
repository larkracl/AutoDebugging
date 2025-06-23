# scripts/checkers/rt_checkers/name_error_checker.py
import parso
from parso.python import tree as pt
import builtins
import sys

from checkers.base_checkers import BaseParsoChecker
from symbol_table import Scope

class RTNameErrorParsoChecker(BaseParsoChecker):
    MSG_ID_PREFIX = 'E'
    NAME = 'rt-name-error-parso'
    node_types = ('name',)
    MSGS = {'0101': ("NameError: Name '%s' is not defined (RT-Parso)", 'undefined-variable-rt-parso', '')}

    def _is_attribute_name(self, node: parso.tree.Leaf) -> bool:
        """이름이 `obj.name` 형태의 속성인지 확인합니다."""
        parent = node.parent
        return bool(parent and parent.type == 'trailer' and len(parent.children) > 1 and parent.children[0].value == '.')

    def check(self, node: parso.tree.Leaf, current_scope: Scope):
        """심볼 테이블을 사용하여 정의되지 않은 변수를 검사합니다."""
        # 속성 접근(a.b의 b)이나 내장 함수는 검사 대상에서 제외
        if self._is_attribute_name(node) or hasattr(builtins, node.value):
            return
            
        # 심볼 테이블에서 이름 검색. 찾지 못하면 오류 보고
        if current_scope and current_scope.lookup(node.value) is None:
            self.add_message(node, '0101', (node.value,))