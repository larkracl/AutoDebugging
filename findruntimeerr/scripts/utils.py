# scripts/utils.py
import astroid
import parso
from parso.python import tree as pt
import sys
from typing import Optional, Set, Union, List, Dict, Any, cast
import traceback
import importlib.util # 'check_module_exists'를 위해 import

# symbol_table.py에서 클래스 import
from symbol_table import Symbol, Scope, SymbolType

# 타입 정의
AstroidScopeNode = Union[astroid.Module, astroid.FunctionDef, astroid.Lambda, astroid.ClassDef, astroid.GeneratorExp, astroid.ListComp, astroid.SetComp, astroid.DictComp]
ParsoScopeNode = Union[pt.Module, pt.Function, pt.Class, pt.Lambda]

# --- Parso 기반 함수 (스코프 채우기용) ---

def _add_parso_target_names_to_scope(target_node: parso.tree.BaseNode, scope: Scope, symbol_type: SymbolType = SymbolType.VARIABLE):
    """Helper: Parso 할당/정의 대상 노드에서 변수 이름을 추출하여 주어진 스코프에 Symbol로 정의합니다."""
    node_type = target_node.type
    if node_type == 'param':
        if hasattr(target_node, 'children') and len(target_node.children) > 0:
             _add_parso_target_names_to_scope(target_node.children[0], scope, symbol_type)
        return
    if node_type == 'name':
        if isinstance(target_node, parso.tree.Leaf):
             scope.define(Symbol(target_node.value, symbol_type, target_node))
    elif node_type in ('testlist_star_expr', 'exprlist', 'testlist', 'atom', 'tfpdef') and hasattr(target_node, 'children'):
        for child in target_node.children:
            _add_parso_target_names_to_scope(child, scope, symbol_type)


def _populate_scope_from_node_recursive(node: parso.tree.BaseNode, current_scope: Scope):
    """
    주어진 Parso 노드와 그 하위를 재귀적으로 탐색하며 정의를 찾아 현재 스코프에 추가합니다.
    새로운 스코프(함수/클래스)를 만나면 재귀를 중단합니다.
    """
    node_type = node.type

    # 1. 새로운 스코프(함수/클래스) 정의
    if node_type in ('funcdef', 'classdef'):
        name_node = node.children[1]
        if name_node.type == 'name' and isinstance(name_node, parso.tree.Leaf):
            symbol_type = SymbolType.FUNCTION if node_type == 'funcdef' else SymbolType.CLASS
            current_scope.define(Symbol(name_node.value, symbol_type, name_node))
        return # 재귀 중단

    # 2. 다른 모든 정의 구문 처리
    
    # --- 여기가 수정된 부분: Import 처리 로직을 안정적인 원래 버전으로 복원 ---
    # `from a.b import c`에서 `a`를 심볼로 등록하는 복잡한 로직을 제거합니다.
    # 오직 `get_defined_names()`를 통해 현재 스코프에 정의되는 이름만 등록합니다.
    if node_type == 'simple_stmt' and len(node.children) > 0 and node.children[0].type in ('import_name', 'import_from'):
        import_stmt = node.children[0]
        try:
            for name_leaf in import_stmt.get_defined_names():
                if name_leaf.value != '*':
                    symbol_type = SymbolType.MODULE if import_stmt.type == 'import_name' else SymbolType.IMPORTED_NAME
                    current_scope.define(Symbol(name_leaf.value, symbol_type, name_leaf))
        except Exception:
            # Parso 내부 오류 발생 시 조용히 무시
            pass
            
    # 일반/주석 할당문
    elif node_type == 'simple_stmt' and len(node.children) > 0 and node.children[0].type == 'expr_stmt':
        expr_stmt = node.children[0]
        if len(expr_stmt.children) >= 2 and expr_stmt.children[1].type == 'operator' and expr_stmt.children[1].value in ('=', ':'):
            _add_parso_target_names_to_scope(expr_stmt.children[0], current_scope)
    # For 루프 변수
    elif node_type == 'for_stmt':
        if len(node.children) >= 2: _add_parso_target_names_to_scope(node.children[1], current_scope)
    # With ... as 변수
    elif node_type == 'with_item':
        as_node = next((c for c in node.children if isinstance(c, parso.tree.Leaf) and c.value == 'as'), None)
        if as_node:
            next_sibling = as_node.get_next_sibling()
            if next_sibling:
                _add_parso_target_names_to_scope(next_sibling, current_scope)
    # Except ... as 변수
    elif node_type == 'except_clause':
        as_node = next((c for c in node.children if isinstance(c, parso.tree.Leaf) and c.value == 'as'), None)
        if as_node:
            next_sibling = as_node.get_next_sibling()
            if next_sibling and next_sibling.type == 'name':
                current_scope.define(Symbol(next_sibling.value, SymbolType.VARIABLE, next_sibling))
    # Walrus 연산자
    elif node_type == 'namedexpr_test':
        if len(node.children) > 0 and node.children[0].type == 'name' and isinstance(node.children[0], parso.tree.Leaf):
            current_scope.define(Symbol(node.children[0].value, SymbolType.VARIABLE, node.children[0]))

    # 3. 다른 모든 자식 노드는 재귀적으로 하위 탐색
    if hasattr(node, 'children'):
        for child in node.children:
            _populate_scope_from_node_recursive(child, current_scope)


def populate_scope_from_parso(scope: Scope):
    """
    주어진 Parso 스코프 노드를 분석하여 심볼 테이블(Scope 객체)을 채웁니다.
    """
    scope_node = scope.node
    try:
        # 1. 함수/람다 매개변수 먼저 수집
        if isinstance(scope_node, (pt.Function, pt.Lambda)):
            for param in scope_node.get_params():
                _add_parso_target_names_to_scope(param, scope, SymbolType.PARAMETER)

        # 2. 현재 스코프의 본문(suite)에 있는 직계 자식 노드들 순회
        nodes_to_process = []
        if isinstance(scope_node, pt.Module):
            nodes_to_process = scope_node.children
        elif hasattr(scope_node, 'get_suite'): # Function, Class
             suite = scope_node.get_suite()
             if suite: nodes_to_process = suite.children

        for node in nodes_to_process:
            _populate_scope_from_node_recursive(node, scope)

    except Exception:
         # 릴리즈 버전에서는 오류를 조용히 무시
         pass

def check_module_exists(module_name: str) -> bool:
    """
    주어진 이름의 모듈이 현재 환경에 설치되어 있는지 확인합니다.
    'a.b.c' 같은 경우, 최상위 모듈인 'a'만 확인합니다.
    """
    # 상대 경로나 빈 이름은 검사하지 않고 True 반환 (오탐 방지)
    if not module_name or module_name.startswith('.'):
        return True
    
    try:
        # 'a.b.c' -> 'a'
        top_level_module = module_name.split('.')[0]
        # find_spec이 None을 반환하면 모듈이 없는 것
        return importlib.util.find_spec(top_level_module) is not None
    except Exception:
        # find_spec 에서 예외 발생 시, 검사 불가로 간주하고 일단 통과
        return True

# --- Astroid 기반 함수 (변경 없음) ---
def get_type_astroid(node: astroid.NodeNG) -> Optional[str]:
    """
    astroid 노드의 타입을 추론하여 문자열로 반환합니다.
    """
    try:
        inferred_list = list(node.infer(context=None))

        if not inferred_list or inferred_list[0] is astroid.Uninferable:
            if isinstance(node, astroid.Const): return type(node.value).__name__
            elif isinstance(node, astroid.List): return 'list'
            elif isinstance(node, astroid.Tuple): return 'tuple'
            elif isinstance(node, astroid.Dict): return 'dict'
            elif isinstance(node, astroid.Set): return 'set'
            return None

        primary_type = inferred_list[0]

        if hasattr(primary_type, 'pytype'):
            try: return primary_type.pytype()
            except Exception: pass
        if hasattr(primary_type, 'qname') and isinstance(primary_type.qname, str):
            return primary_type.qname
        if hasattr(primary_type, 'name') and isinstance(primary_type.name, str):
            return primary_type.name
        if isinstance(primary_type, astroid.Const):
            return type(primary_type.value).__name__
            
        return primary_type.__class__.__name__

    except (astroid.InferenceError, Exception):
        return None

def is_compatible_astroid(type1_fq: Optional[str], type2_fq: Optional[str], op: str) -> bool:
    """두 타입이 주어진 연산자에 대해 호환되는지 확인합니다."""
    if type1_fq is None or type2_fq is None: return True
    type1 = type1_fq.split('.')[-1].lower()
    type2 = type2_fq.split('.')[-1].lower()
    numeric_types = ("int", "float", "complex", "bool")
    sequence_types = ("str", "list", "tuple", "bytes", "bytearray", "range")
    set_types = ("set", "frozenset")
    mapping_types = ("dict",)
    if type1 in numeric_types and type2 in numeric_types:
        if op in ("+", "-", "*", "/", "//", "%", "**", "<", "<=", ">", ">=", "==", "!="):
            if "complex" in (type1, type2) and op in ("<", "<=", ">", ">="): return False
            return True
        if type1 in ("int", "bool") and type2 in ("int", "bool") and op in ("&", "|", "^", "<<", ">>", "~"): return True
    if type1 in sequence_types and type2 in sequence_types:
        if type1 == type2 and op == '+': return True
        if type1 in ("str", "tuple", "list", "bytes", "bytearray") and type1 == type2 and op in ("<", "<=", ">", ">="): return True
        if op in ("==", "!="): return True
    if op == '*':
        if (type1 in sequence_types and type2 == 'int') or (type1 == 'int' and type2 in sequence_types): return True
    is_type1_numeric = type1 in numeric_types
    is_type2_numeric = type2 in numeric_types
    if op in ('+', '-', '/', '//', '%', '**') and (is_type1_numeric != is_type2_numeric): return False
    if op == '%' and type1 == "str": return True
    if type1 in set_types and type2 in set_types:
         if op in ("|", "&", "-", "^", "<=", "<", ">=", ">", "==", "!="): return True
    if op in ("in", "not in"):
        if type2 in sequence_types or type2 in set_types or type2 in mapping_types: return True
    if op in ('and', 'or', 'not', 'is', 'is not'): return True
    if op in ('+', '-') and type1 in numeric_types: return True
    return False