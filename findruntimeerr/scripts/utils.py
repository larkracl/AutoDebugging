# utils.py (collect_defined_variables_parso 대폭 개선)
import astroid
import parso
from parso.python import tree as pt
import sys
from typing import Optional, Set, Union, List, Dict, Any, cast, Tuple
import traceback
import importlib.util

from astroid.nodes import Module as AstroidModule, FunctionDef as AstroidFunctionDef, Lambda as AstroidLambda, \
    ClassDef as AstroidClassDef, GeneratorExp as AstroidGeneratorExp, ListComp as AstroidListComp, \
    SetComp as AstroidSetComp, DictComp as AstroidDictComp

AstroidScopeNode = Union[AstroidModule, AstroidFunctionDef, AstroidLambda, AstroidClassDef, AstroidGeneratorExp, AstroidListComp, AstroidSetComp, AstroidDictComp]
ParsoScopeNode = Union[pt.Module, pt.Function, pt.Class, pt.Lambda]

def _add_parso_target_names(target_node: parso.tree.BaseNode, defined_vars: Set[str]):
    node_type = target_node.type
    if node_type == 'name':
        if isinstance(target_node, parso.tree.Leaf):
             defined_vars.add(target_node.value)
    elif node_type in ('testlist_star_expr', 'exprlist', 'testlist', 'atom', 'tfpdef') and hasattr(target_node, 'children'):
        for child in target_node.children:
            if child.type == 'name' and isinstance(child, parso.tree.Leaf):
                defined_vars.add(child.value)
            elif not isinstance(child, parso.tree.Leaf) and hasattr(child, 'children') and \
                 child.type not in ('operator', 'keyword') and \
                 (not hasattr(child, 'value') or child.value not in [',', '(', ')', '[', ']', '{', '}', ':']):
                 _add_parso_target_names(child, defined_vars)

def collect_defined_variables_parso(
    scope_node: ParsoScopeNode
) -> Tuple[Set[str], List[Tuple[str, parso.tree.BaseNode, str]], List[Tuple[str, str, parso.tree.BaseNode]]]:
    defined_vars: Set[str] = set()
    definitions: List[Tuple[str, parso.tree.BaseNode, str]] = []
    imports: List[Tuple[str, str, parso.tree.BaseNode]] = []
    try:
        # 1. 함수/람다 매개변수
        if isinstance(scope_node, (pt.Function, pt.Lambda)):
            for param in scope_node.get_params():
                _add_parso_target_names(param.name, defined_vars)

        # 2. 클래스 내부 정의 (메서드, 클래스 변수 - Class 스코프에서만)
        if isinstance(scope_node, pt.Class):
            class_suite = scope_node.get_suite()
            if class_suite:
                for node_in_class in class_suite.children:
                    if node_in_class.type == 'funcdef':
                        name_node = node_in_class.children[1]
                        if name_node.type == 'name' and isinstance(name_node, parso.tree.Leaf):
                            var_name = name_node.value
                            defined_vars.add(var_name)
                            definitions.append((var_name, node_in_class, 'function'))
                    elif node_in_class.type == 'simple_stmt' and len(node_in_class.children) > 0 and \
                         node_in_class.children[0].type == 'expr_stmt':
                        assign_expr = node_in_class.children[0]
                        if len(assign_expr.children) >= 3 and assign_expr.children[1].type == 'operator' and \
                           assign_expr.children[1].value == '=':
                            _add_parso_target_names(assign_expr.children[0], defined_vars)
                        elif len(assign_expr.children) >= 2 and assign_expr.children[1].type == 'operator' and \
                             assign_expr.children[1].value == ':':
                            _add_parso_target_names(assign_expr.children[0], defined_vars)

        # 3. 현재 스코프의 직계 자식 노드들 순회 (Module, Function suite, Class suite)
        nodes_to_traverse = []
        if isinstance(scope_node, pt.Module): nodes_to_traverse = scope_node.children
        elif hasattr(scope_node, 'get_suite'):
            suite = scope_node.get_suite()
            if suite: nodes_to_traverse = suite.children
        # Lambda의 body는 표현식이므로, 여기서는 직접 순회하지 않고 아래 iter_preorder로 Walrus 처리

        for node in nodes_to_traverse:
            node_type = node.type
            # A. 할당문 (단순, 주석)
            if node_type == 'simple_stmt' and len(node.children) > 0:
                stmt_expr = node.children[0]
                if stmt_expr.type == 'expr_stmt' and len(stmt_expr.children) >= 2:
                    first_child = stmt_expr.children[0]
                    second_child = stmt_expr.children[1]
                    if second_child.type == 'operator':
                        if second_child.value == '=' and len(stmt_expr.children) >=3: # target = value
                            _add_parso_target_names(first_child, defined_vars)
                        elif second_child.value == ':': # target : type [= value]
                            _add_parso_target_names(first_child, defined_vars)
            # B. 함수/클래스 정의
            elif node_type in ('funcdef', 'classdef'):
                name_node = node.children[1]
                if name_node.type == 'name' and isinstance(name_node, parso.tree.Leaf):
                    var_name = name_node.value
                    defined_vars.add(var_name)
                    def_type = 'function' if node_type == 'funcdef' else 'class'
                    definitions.append((var_name, node, def_type))
            # C. Import 문
            elif node_type == 'simple_stmt' and len(node.children) > 0:
                import_stmt = node.children[0]
                if import_stmt.type in ('import_name', 'import_from'):
                    try:
                        for name_leaf in import_stmt.get_defined_names():
                            imported_name = name_leaf.value
                            if imported_name != '*':
                                defined_vars.add(imported_name)
                                top_level_module = imported_name.split('.')[0] # 기본
                                if import_stmt.type == 'import_from':
                                    # from X.Y import Z -> X
                                    # from .X import Y -> .
                                    module_path_node = import_stmt.children[1] # index of module path
                                    if module_path_node.type == 'dotted_name' and module_path_node.children:
                                        top_level_module = module_path_node.children[0].value
                                    elif isinstance(module_path_node, parso.tree.Leaf): # from . import X
                                        top_level_module = module_path_node.value
                                if top_level_module:
                                    imports.append((imported_name, top_level_module, import_stmt))
                    except Exception as e: print(f"Error parsing import names: {e}", file=sys.stderr)
            # D. For 루프 변수
            elif node_type == 'for_stmt' and len(node.children) >= 2:
                _add_parso_target_names(node.children[1], defined_vars) # children[1] is the target(s)
            # E. With ... as 변수
            elif node_type == 'with_stmt':
                 for item_child in node.children:
                      if item_child.type == 'with_item':
                           for sub_idx, sub_item_child in enumerate(item_child.children):
                               if isinstance(sub_item_child, parso.tree.Leaf) and sub_item_child.value == 'as':
                                    if sub_idx + 1 < len(item_child.children):
                                         _add_parso_target_names(item_child.children[sub_idx+1], defined_vars)
                                    break
            # F. Except ... as 변수
            elif node_type == 'try_stmt':
                 for child_of_try in node.children: # try_stmt -> suite, except_clause, ...
                      if child_of_try.type == 'except_clause':
                           # except_clause -> 'except' [test ['as' name]] ':' suite
                           as_keyword_index = -1
                           for i, sub_node in enumerate(child_of_try.children):
                               if isinstance(sub_node, parso.tree.Leaf) and sub_node.value == 'as':
                                   as_keyword_index = i; break
                           if as_keyword_index != -1 and as_keyword_index + 1 < len(child_of_try.children):
                               name_after_as = child_of_try.children[as_keyword_index + 1]
                               if name_after_as.type == 'name' and isinstance(name_after_as, parso.tree.Leaf):
                                   defined_vars.add(name_after_as.value)
            # G. Walrus operator (name := expr) - 모든 하위 노드에서 찾기
            if hasattr(node, 'iter_preorder'):
                for sub_node in node.iter_preorder(): # iter_preorder는 해당 노드 포함 하위 모두
                    if sub_node.type == 'namedexpr_test': # NAME ':=' test
                         if len(sub_node.children) > 0 and sub_node.children[0].type == 'name':
                              if isinstance(sub_node.children[0], parso.tree.Leaf):
                                   defined_vars.add(sub_node.children[0].value)
    except Exception as e:
         scope_repr = repr(scope_node); print(f"Error in collect_defined_variables_parso for {scope_repr[:100]}...: {e}", file=sys.stderr); traceback.print_exc(file=sys.stderr)
    return defined_vars, definitions, imports

def check_module_exists(module_name: str) -> bool:
    if not module_name or module_name.startswith('.'): # 상대경로는 현재 파일 위치 기준으로 find_spec이 어려울 수 있음
        return True # 일단 존재한다고 가정하거나, 더 정교한 경로 해석 필요
    try:
        spec = importlib.util.find_spec(module_name)
        return spec is not None
    except Exception: # ImportError, ValueError for invalid names etc.
        return False

# --- Astroid 기반 함수 (이전과 동일) ---
def get_type_astroid(node: astroid.NodeNG) -> Optional[str]:
    try:
        inferred_list = list(node.infer(context=None));
        if not inferred_list or inferred_list[0] is astroid.Uninferable:
            if isinstance(node, astroid.Const): return type(node.value).__name__
            elif isinstance(node, astroid.List): return 'list'
            elif isinstance(node, astroid.Tuple): return 'tuple'
            elif isinstance(node, astroid.Dict): return 'dict'
            elif isinstance(node, astroid.Set): return 'set'
            elif isinstance(node, astroid.Lambda): return 'function'
            elif isinstance(node, astroid.FunctionDef): return 'function'
            elif isinstance(node, astroid.ClassDef): return 'type'
            return None
        primary_type = inferred_list[0]
        if isinstance(primary_type, astroid.Instance):
            proxied = getattr(primary_type, '_proxied', primary_type)
            return getattr(proxied, 'qname', getattr(proxied, 'name', type(proxied).__name__))
        elif isinstance(primary_type, astroid.ClassDef):
             return getattr(primary_type, 'qname', primary_type.name)
        elif isinstance(primary_type, astroid.FunctionDef):
            return getattr(primary_type, 'qname', 'function')
        elif isinstance(primary_type, astroid.Const):
             return type(primary_type.value).__name__
        return getattr(primary_type, 'qname', getattr(primary_type, 'name', type(primary_type).__name__))
    except astroid.InferenceError: return None
    except Exception as e: node_repr = repr(node); print(f"Error in get_type_astroid for {node_repr[:100]}...: {e}", file=sys.stderr); traceback.print_exc(file=sys.stderr); return None

def is_compatible_astroid(type1_fq: Optional[str], type2_fq: Optional[str], op: str) -> bool:
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
        if type1 in ("str", "tuple", "list", "bytes", "bytearray") and type1 == type2 and op in ("==", "!=", "<", "<=", ">", ">="): return True
    if op == '*' and ((type1 in sequence_types and type2 == 'int') or (type1 == 'int' and type2 in sequence_types)): return True
    if op == '%' and type1 == "str": return True
    if type1 in set_types and type2 in set_types and op in ("|", "&", "-", "^", "<=", "<", ">=", ">", "==", "!="): return True
    if op in ("in", "not in") and (type2 in sequence_types or type2 in set_types or type2 in mapping_types): return True
    if op in ('and', 'or'): return True
    if op == 'not': return True
    if op in ('+', '-') and type1 in numeric_types: return True
    return False

def collect_defined_variables_astroid(scope_node: AstroidScopeNode) -> Set[str]:
     defined_vars: Set[str] = set()
     try:
        if isinstance(scope_node, (astroid.FunctionDef, astroid.Lambda)): defined_vars.update(scope_node.argnames())
        assign_targets = [t.name for an in scope_node.nodes_of_class((astroid.Assign, astroid.AugAssign, astroid.AnnAssign)) for t in an.targets if isinstance(t, astroid.AssignName)]
        defined_vars.update(assign_targets)
        unpacking_targets = [e.name for an in scope_node.nodes_of_class((astroid.Assign, astroid.AnnAssign)) for t in an.targets if isinstance(t, (astroid.Tuple, astroid.List)) for e in t.elts if isinstance(e, astroid.AssignName)]
        defined_vars.update(unpacking_targets)
        import_names = set()
        for imp_node in scope_node.nodes_of_class((astroid.Import, astroid.ImportFrom)):
            for name, alias in imp_node.names:
                if name != '*': import_names.add(alias or name.split('.')[0] if isinstance(imp_node, astroid.Import) else alias or name)
        defined_vars.update(import_names)
        for_targets = [t.name for fn in scope_node.nodes_of_class(astroid.For) for t in [fn.target] if isinstance(t, astroid.AssignName)]
        defined_vars.update(for_targets)
        for_unpack_targets = [e.name for fn in scope_node.nodes_of_class(astroid.For) for t in [fn.target] if isinstance(t, (astroid.Tuple, astroid.List)) for e in t.elts if isinstance(e, astroid.AssignName)]
        defined_vars.update(for_unpack_targets)
        with_targets = [t.name for wn in scope_node.nodes_of_class(astroid.With) for _, ats in wn.items if ats for t in ([ats] if isinstance(ats, astroid.AssignName) else ats.elts if isinstance(ats, (astroid.Tuple, astroid.List)) else []) if isinstance(t, astroid.AssignName)]
        defined_vars.update(with_targets)
        def_names = [dn.name for dn in scope_node.nodes_of_class((astroid.FunctionDef, astroid.ClassDef)) if dn.parent is scope_node]
        defined_vars.update(def_names)
        except_names = [en.name.name for en in scope_node.nodes_of_class(astroid.ExceptHandler) if en.name and isinstance(en.name, astroid.AssignName)]
        defined_vars.update(except_names)
     except Exception as e:
         scope_name = getattr(scope_node, 'name', type(scope_node).__name__); print(f"Error collecting astroid vars in '{scope_name}': {e}", file=sys.stderr); traceback.print_exc(file=sys.stderr)
     return defined_vars