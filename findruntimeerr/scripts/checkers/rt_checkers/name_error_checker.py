# scripts/checkers/rt_checkers/name_error_checker.py (심볼 테이블 사용 방식으로 재작성)
import parso
from parso.python import tree as pt
import builtins
import sys

from checkers.base_checkers import BaseParsoChecker
from symbol_table import Scope

class RTNameErrorParsoChecker(BaseParsoChecker):
    MSG_ID_PREFIX = 'E'; NAME = 'rt-name-error-parso'; node_types = ('name',)
    MSGS = {'0101': ("NameError: Name '%s' is not defined (RT-Parso)", 'undefined-variable-rt-parso', '')}

    def _is_attribute_name(self, node: parso.tree.Leaf) -> bool:
        parent = node.parent
        if parent and parent.type == 'trailer':
            if len(parent.children) == 2 and parent.children[0].type == 'operator' and \
               parent.children[0].value == '.' and parent.children[1] is node:
                return True
        return False

    def _is_keyword_arg_name(self, node: parso.tree.Leaf) -> bool:
        parent = node.parent
        if parent and parent.type == 'argument':
            if len(parent.children) >= 2 and parent.children[0] is node and \
               parent.children[1].type == 'operator' and parent.children[1].value == '=':
                return True
        return False

    def check(self, node: parso.tree.Leaf, current_scope: Scope):
        """
        심볼 테이블(current_scope)을 사용하여 NameError를 검사합니다.
        node: 검사 대상 name Leaf 노드
        current_scope: 해당 노드가 속한 Scope 객체
        """
        # 1. 명백한 제외 조건
        if hasattr(builtins, node.value): return
        if self._is_attribute_name(node): return
        if self._is_keyword_arg_name(node): return

        # 2. SyntaxError로 인해 생성된 error_node 내부의 이름은 무시
        #    (정확한 스코프 분석이 불가능하므로)
        temp_parent = node.parent
        while temp_parent:
            if temp_parent.type == 'error_node':
                return
            if temp_parent.type in ('funcdef', 'classdef', 'file_input'): # 스코프 경계
                break
            temp_parent = temp_parent.parent


        # 3. 현재 스코프와 상위 스코프에서 이름(Symbol)을 찾는다.
        try:
            if current_scope:
                # lookup은 현재 스코프 -> 부모 스코프 -> built-in 순으로 검색
                symbol = current_scope.lookup(node.value)
                if symbol is None:
                    # 모든 스코프에서 찾지 못했으면 NameError
                    self.add_message(node, '0101', (node.value,))
            else:
                 # 스코프를 찾을 수 없는 예외적인 경우
                 print(f"Warning: Could not find scope for node '{node.value}'", file=sys.stderr)

        except Exception as e:
            # 체커 실행 중 오류 발생 시
            print(f"Error in RTNameErrorParsoChecker for '{node.value}': {e}", file=sys.stderr)