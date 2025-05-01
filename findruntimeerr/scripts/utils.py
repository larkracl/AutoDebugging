# scripts/utils.py
import sys
import parso
# parso 노드 타입 import
from parso.tree import Node, Leaf, BaseNode # BaseNode는 Node와 Leaf의 공통 부모
from parso.python import tree as parso_tree # 구체적인 타입들 (Function, Class 등)
from typing import Optional, Set, Union, List, Dict, Any

# --- 타입 추론 함수 (매우 간소화됨) ---
def get_type(node: BaseNode) -> Optional[str]: # BaseNode 사용
    """parso 노드의 타입을 간단하게 추론합니다."""
    try:
        node_type = node.type # parso 노드 타입 (문자열)

        if node_type == 'number':
            val_str = node.value
            if '.' in val_str or 'e' in val_str.lower(): return 'float'
            if 'j' in val_str.lower(): return 'complex' # 복소수 추가
            return 'int'
        elif node_type == 'string':
            # 'rb' 와 같은 prefix 확인하여 bytes 구분 시도
            code = node.get_code(include_prefix=True).lower()
            if code.startswith('b') or code.startswith('rb'): return 'bytes'
            if code.startswith('u'): return 'str' # 유니코드 명시
            # TODO: f-string, raw string 등 더 정확한 구분 필요
            return 'str' # 기본값 str
        elif node_type == 'keyword':
            if node.value in ('True', 'False'): return 'bool'
            if node.value == 'None': return 'NoneType'
        elif node_type == 'name':
             return 'variable' # 또는 node.value (타입은 아님)
        elif node_type in ('funcdef', 'lambdef'):
             return 'function'
        elif node_type == 'classdef':
             class_name_node = node.children[1] # 'class' 키워드 다음 이름
             if class_name_node.type == 'name': return class_name_node.value
             return 'class'
        elif node_type == 'atom_expr': # 리스트, 튜플, 딕셔너리, 셋 리터럴
             if node.children:
                 first_child = node.children[0]
                 if first_child.type == 'atom':
                      op_char = first_child.children[0].value
                      if op_char == '[': return 'list'
                      if op_char == '(': return 'tuple'
                      if op_char == '{':
                           if len(first_child.children) > 2 and first_child.children[1].type == 'dictorsetmaker':
                               if ':' in [c.value for c in first_child.children[1].children if c.type=='operator']: return 'dict'
                               else: return 'set'
                           elif len(first_child.children) == 2: return 'dict' # {}
                           else: return 'set' # PEP 274: 빈 셋 리터럴 없음, set() 사용
        # TODO: 더 많은 타입 추론 (예: 함수 호출 결과, 인스턴스 생성) - parso로는 매우 제한적

    except Exception as e:
        print(f"Unexpected error in get_type for parso node {node!r}: {e}", file=sys.stderr)
    return None

# --- 타입 호환성 검사 (개선됨) ---
def is_compatible(type1: Optional[str], type2: Optional[str], op: str) -> bool:
    """두 타입이 주어진 연산에 대해 호환되는지 확인합니다."""
    # 추론 불가/불확실 타입은 일단 호환 간주
    if type1 is None or type2 is None or \
       type1.lower() == 'unknown' or type2.lower() == 'unknown' or \
       type1 in ('CallResult', 'variable', 'Name') or type2 in ('CallResult', 'variable', 'Name'):
        return True

    if type1 == type2: return True

    numeric_types = ("int", "float", "complex", "bool")
    sequence_types = ("str", "list", "tuple", "bytes", "bytearray")
    set_types = ("set", "frozenset")
    mapping_types = ("dict",)

    # 숫자 타입 간 연산
    if type1 in numeric_types and type2 in numeric_types:
        if op in ("+", "-", "*", "/", "//", "%", "**", "<", "<=", ">", ">=", "==", "!="): return True
        if type1 in ("int", "bool") and type2 in ("int", "bool") and op in ("&", "|", "^", "<<", ">>"): return True

    # 시퀀스 타입 연산
    if type1 in sequence_types and type2 in sequence_types and type1 == type2 and op == '+': return True
    if type1 in sequence_types and type2 == 'int' and op == '*': return True
    if type1 == 'int' and type2 in sequence_types and op == '*': return True
    if type1 == "str" and type2 == "str" and op in ("==", "!=", "<", "<=", ">", ">="): return True

    # 문자열 포매팅
    if type1 == "str" and op == '%': return True

    # Set 연산
    if type1 in set_types and type2 in set_types:
         if op in ("|", "&", "-", "^", "<=", "<", ">=", ">", "==", "!="): return True

    # 멤버십 테스트
    if op in ("in", "not in"):
        if type2 in sequence_types or type2 in set_types or type2 in mapping_types: return True

    # bool 연산 (and, or)
    if op in ('and', 'or'): return True # 모든 타입 가능

    # 단항 연산 (is_compatible 호출 전에 처리하는 것이 더 나을 수 있음)
    if op in ('not', '+', '-', '~'): # type1만 사용됨
         if op == 'not': return True # 대부분 타입 가능
         if op in ('+', '-') and type1 in numeric_types: return True
         if op == '~' and type1 == 'int': return True


    return False

# --- 정의된 변수 수집 (parso 스코프 노드 사용 - Union 타입 수정) ---
def collect_defined_variables(scope_node: Union[parso_tree.Module, parso_tree.Function, parso_tree.Class, parso_tree.Lambda]) -> Set[str]:
    """주어진 parso 스코프 내에서 정의된 이름을 수집합니다."""
    defined_vars: Set[str] = set()
    try:
        # 함수/람다 매개변수
        if isinstance(scope_node, (parso_tree.Function, parso_tree.Lambda)):
            for param in scope_node.get_params():
                if isinstance(param.name, parso_tree.Name): # param.name 이 Name 객체인지 확인
                    defined_vars.add(param.name.value)
                # TODO: 복잡한 파라미터 (튜플 언패킹 등) 처리

        # 클래스 내부: 메서드/클래스 변수
        elif isinstance(scope_node, parso_tree.Class):
             class_suite = scope_node.get_suite()
             if class_suite:
                 for node_in_class in class_suite.children:
                      if node_in_class.type == 'funcdef':
                           if len(node_in_class.children) > 1 and node_in_class.children[1].type == 'name':
                                defined_vars.add(node_in_class.children[1].value)
                      elif node_in_class.type == 'simple_stmt':
                           assign_node = node_in_class.children[0]
                           if assign_node.type == 'expr_stmt':
                               target = assign_node.children[0]
                               # 클래스 변수 할당 (단순 이름)
                               if target.type == 'name': defined_vars.add(target.value)
                               # TODO: AnnAssign, AugAssign 등 추가

        # 스코프 본문 순회
        nodes_to_check = []
        if isinstance(scope_node, parso_tree.Module): nodes_to_check = scope_node.children
        elif hasattr(scope_node, 'get_suite'): # Function, Class, Lambda
             suite = scope_node.get_suite()
             if suite: nodes_to_check = suite.children

        for node in nodes_to_check:
            # 할당문
            if node.type == 'simple_stmt' and node.children[0].type == 'expr_stmt':
                 stmt_children = node.children[0].children
                 # A = B, A, B = C 등
                 if len(stmt_children) > 1 and stmt_children[1].type == 'operator' and stmt_children[1].value == '=':
                     target = stmt_children[0]
                     _add_target_names_parso(target, defined_vars)
                 # A : int = B (AnnAssign 유사 패턴)
                 elif len(stmt_children) >= 3 and stmt_children[1].type == ':' and len(stmt_children) > 3 and stmt_children[3].type == 'operator' and stmt_children[3].value == '=':
                     target = stmt_children[0]
                     if target.type == 'name': defined_vars.add(target.value)
                 # A += B (AugAssign 유사 패턴) - 이미 정의되어 있어야 함
                 elif len(stmt_children) > 1 and stmt_children[1].type == 'augassign':
                      target = stmt_children[0]
                      if target.type == 'name': defined_vars.add(target.value)

            # For 루프 변수
            elif node.type == 'for_stmt':
                 target_list = node.children[1] # exprlist
                 _add_target_names_parso(target_list, defined_vars)
            # Import 문
            elif node.type == 'simple_stmt' and node.children[0].type == 'import_name':
                 dotted_as_names = node.children[0].children[1]
                 for name_node in dotted_as_names.children:
                      if name_node.type == 'dotted_as_name':
                           if len(name_node.children) == 3: defined_vars.add(name_node.children[2].value) # as name
                           else: # a.b.c -> c만 추가 (선택적)
                                last_name_leaf = name_node.children[0].get_last_leaf()
                                if last_name_leaf.type == 'name': defined_vars.add(last_name_leaf.value)
                      elif name_node.type == ',': continue
            elif node.type == 'simple_stmt' and node.children[0].type == 'import_from':
                 import_target = node.children[0].children[-1]
                 if import_target.type == 'import_as_names':
                      for name_node in import_target.children:
                           if name_node.type == 'import_as_name':
                                if len(name_node.children) == 3: defined_vars.add(name_node.children[2].value) # as name
                                else: defined_vars.add(name_node.children[0].value) # original name
                           elif name_node.type == ',': continue
                 elif import_target.type == 'import_as_name':
                     if len(import_target.children) == 3: defined_vars.add(import_target.children[2].value)
                     else: defined_vars.add(import_target.children[0].value)
            # 함수/클래스 정의
            elif node.type in ('funcdef', 'classdef'):
                 if len(node.children) > 1 and node.children[1].type == 'name':
                     defined_vars.add(node.children[1].value)
            # With 문 변수
            elif node.type == 'with_stmt':
                 for item in node.children:
                      if item.type == 'with_item' and len(item.children) == 3 and item.children[1].value == 'as':
                           _add_target_names_parso(item.children[2], defined_vars)

    except Exception as e:
         print(f"Error collecting defined variables in scope {getattr(scope_node, 'name', scope_node.type)}: {e}", file=sys.stderr)

    return defined_vars

def _add_target_names_parso(target_node: BaseNode, defined_vars: Set[str]):
    """parso 할당/루프 대상 노드에서 변수 이름을 추출합니다."""
    if target_node.type == 'name':
         defined_vars.add(target_node.value)
    elif target_node.type in ('testlist_star_expr', 'exprlist', 'testlist', 'arglist', 'atom') : # atom 추가 (괄호 있는 튜플)
         if hasattr(target_node, 'children'):
             for child in target_node.children:
                  if child.type != ',' and child.value not in '()[]{}': # 구분자 제외
                       _add_target_names_parso(child, defined_vars)