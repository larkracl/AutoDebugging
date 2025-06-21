# scripts/checkers/rt_checkers/name_error_checker.py (심볼 테이블 사용 방식으로 재작성)
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

    def _is_definition_name_itself(self, node: parso.tree.Leaf) -> bool:
        parent = node.parent
        if not parent: return False
        parent_type = parent.type

        # 1. 정상적인 함수/클래스 정의 이름
        if parent_type in ('funcdef', 'classdef'):
            if len(parent.children) > 1 and parent.children[1] is node:
                return True

        # 2. SyntaxError로 인해 깨진 노드 예외 처리 (새로 추가/수정)
        if parent_type == 'error_node':
            children_values = [c.value for c in parent.children if isinstance(c, parso.tree.Leaf)]
            if ('def' in children_values or 'class' in children_values) and node.value in children_values:
                return True

        # 3. 함수 파라미터 이름
        if parent_type == 'param':
            if hasattr(parent, 'name') and parent.name is node:
                return True
            if len(parent.children) > 0 and parent.children[0].type == 'name' and parent.children[0] is node:
                return True
        return False

    def _is_part_of_lhs_assignment(self, node: parso.tree.Leaf) -> bool:
        parent = node.parent
        if not parent: return False

        grandparent = parent.parent
        if not grandparent or grandparent.type != 'expr_stmt':
            # Walrus 연산자 케이스: name := test
            if parent.type == 'namedexpr_test' and len(parent.children) > 0 and parent.children[0] is node:
                return True
            return False

        # 이제 grandparent가 expr_stmt인 것이 거의 확실함
        # expr_stmt의 첫 번째 자식이 LHS 전체를 담고 있음
        lhs_expression_node = grandparent.children[0]

        # 현재 node가 이 LHS 표현식 노드의 일부인지 확인
        # (단순 이름, 튜플/리스트 언패킹 모두 포함)
        q = [lhs_expression_node]
        visited = {lhs_expression_node}
        is_on_lhs = False
        while q:
            current = q.pop(0)
            if current is node:
                is_on_lhs = True
                break
            if hasattr(current, 'children'):
                for child in current.children:
                    if child not in visited:
                        q.append(child)
                        visited.add(child)
        
        # LHS에 있고, 그 뒤에 할당 관련 연산자가 오는지 확인
        if is_on_lhs:
            if len(grandparent.children) > 1 and grandparent.children[1].type == 'operator':
                op_value = grandparent.children[1].value
                if op_value == '=' or op_value == ':':
                    return True

        return False

    def check(self, node: parso.tree.Leaf, current_scope: Scope):
        if hasattr(builtins, node.value): return
        if self._is_attribute_name(node): return
        if self._is_keyword_arg_name(node): return
        temp_parent = node.parent
        while temp_parent:
            if temp_parent.type == 'error_node':
                return
            if temp_parent.type in ('funcdef', 'classdef', 'file_input'):
                break
            temp_parent = temp_parent.parent
        try:
            if current_scope:
                symbol = current_scope.lookup(node.value)
                if symbol is None:
                    self.add_message(node, '0101', (node.value,))
            else:
                pass
        except Exception as e:
            pass