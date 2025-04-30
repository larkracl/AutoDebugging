# utils.py
import astroid
import sys
from typing import Optional, Set, Union, List, Dict, Any, Union

# --- 타입 추론 함수 ---
def get_type(node: astroid.NodeNG) -> Optional[str]:
    """astroid 노드의 타입을 추론합니다 (단일 타입 우선)."""
    try:
        inferred_list = list(node.infer())
        if not inferred_list or inferred_list[0] is astroid.Uninferable:
            if isinstance(node, astroid.Name): return 'Name'
            if isinstance(node, astroid.Call): return 'CallResult'
            return None

        inferred = inferred_list[0]

        if isinstance(inferred, astroid.Const):
            return type(inferred.value).__name__
        elif isinstance(inferred, astroid.List):
            return "list"
        elif isinstance(inferred, astroid.Tuple):
            return "tuple"
        elif isinstance(inferred, astroid.Dict):
            return "dict"
        elif isinstance(inferred, astroid.Set):
             return "set"
        elif isinstance(inferred, astroid.FunctionDef):
            return "function"
        elif isinstance(inferred, astroid.ClassDef):
            return inferred.name
        elif isinstance(inferred, astroid.Instance):
             try: return inferred.pytype()
             except (AttributeError, TypeError): return inferred.name if hasattr(inferred, 'name') else 'Instance'
        elif isinstance(inferred, astroid.Module):
            return "module"
        elif isinstance(inferred, astroid.Name):
            if inferred.name in ('True', 'False'): return 'bool'
            return 'variable'
        elif isinstance(inferred, astroid.Lambda):
             return "function"
        elif isinstance(inferred, astroid.Call):
            try:
                 func_defs = list(inferred.func.infer())
                 if func_defs and func_defs[0] is not astroid.Uninferable:
                     actual_func = func_defs[0]
                     if isinstance(actual_func, astroid.FunctionDef):
                          if actual_func.returns:
                               return_type_inferred = list(actual_func.returns.infer())
                               if return_type_inferred and return_type_inferred[0] is not astroid.Uninferable:
                                   return get_type(return_type_inferred[0])
                     if hasattr(actual_func, 'name'):
                         if actual_func.name == 'len': return 'int'
                         if actual_func.name == 'str': return 'str'
                 return 'CallResult'
            except astroid.InferenceError: return 'CallResult'
    except astroid.InferenceError: return None
    except Exception as e:
        print(f"Unexpected error in get_type for node {node!r}: {e}", file=sys.stderr)
        return None
    return None

# --- 타입 호환성 검사 ---
def is_compatible(type1: Optional[str], type2: Optional[str], op: str) -> bool:
    """두 타입이 주어진 연산에 대해 호환되는지 확인합니다."""
    if type1 is None or type2 is None or type1.lower() == 'unknown' or type2.lower() == 'unknown' or type1 == 'CallResult' or type2 == 'CallResult' or type1 == 'variable' or type2 == 'variable' or type1 == 'Name' or type2 == 'Name':
        return True # 추론 불가 시 호환 간주

    if type1 == type2: return True

    numeric_types = ("int", "float", "complex", "bool")
    sequence_types = ("str", "list", "tuple", "bytes", "bytearray") # bytes 추가
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
    if type1 == "str" and type2 == "str" and op in ("==", "!=", "<", "<=", ">", ">="): return True # str 비교


    # Set 연산
    if type1 in set_types and type2 in set_types:
         if op in ("|", "&", "-", "^", "<=", "<", ">=", ">", "==", "!="): return True

    # 멤버십 테스트
    if op in ("in", "not in"):
        if type2 in sequence_types or type2 in set_types or type2 in mapping_types: return True

    # TODO: 사용자 정의 클래스 매직 메서드 고려

    return False

# --- 정의된 변수 수집 ---
def collect_defined_variables(scope_node: Union[astroid.FunctionDef, astroid.Module, astroid.ClassDef, astroid.Lambda]) -> Set[str]:
    """주어진 스코프 내에서 정의된 변수/함수/클래스 이름을 수집합니다."""
    defined_vars: Set[str] = set()

    # 함수/람다 매개변수
    if isinstance(scope_node, (astroid.FunctionDef, astroid.Lambda)):
        try:
            args = scope_node.args
            for arg in args.args + args.posonlyargs + args.kwonlyargs: defined_vars.add(arg.name)
            if args.vararg: defined_vars.add(args.vararg)
            if args.kwarg: defined_vars.add(args.kwarg)
        except AttributeError: pass

    # 클래스 스코프: 메서드/클래스 변수
    elif isinstance(scope_node, astroid.ClassDef):
         for node_in_class in scope_node.body:
              if isinstance(node_in_class, (astroid.FunctionDef, astroid.AssignName, astroid.AnnAssign)):
                   # AssignName은 클래스 변수, FunctionDef는 메서드
                   var_name = node_in_class.name if hasattr(node_in_class,'name') else getattr(node_in_class.target, 'name', None)
                   if var_name: defined_vars.add(var_name)

    # 스코프 본문 순회
    if hasattr(scope_node, 'body'):
        current_scope_nodes = scope_node.body if isinstance(scope_node.body, list) else [scope_node.body]
        for node in current_scope_nodes:
            if isinstance(node, astroid.Assign):
                for target in node.targets:
                    if isinstance(target, astroid.Name): defined_vars.add(target.name)
                    elif isinstance(target, (astroid.Tuple, astroid.List)):
                         for elt in target.elts:
                             if isinstance(elt, astroid.Name): defined_vars.add(elt.name)
            elif isinstance(node, astroid.For):
                 _add_target_names(node.target, defined_vars)
            elif isinstance(node, astroid.AnnAssign):
                 if isinstance(node.target, astroid.Name): defined_vars.add(node.target.name)
            elif isinstance(node, astroid.AugAssign):
                 if isinstance(node.target, astroid.Name): defined_vars.add(node.target.name)
            elif isinstance(node, astroid.Import):
                 for alias in node.names: defined_vars.add(alias[1] or alias[0])
            elif isinstance(node, astroid.ImportFrom):
                 for alias in node.names: defined_vars.add(alias[1] or alias[0])
            elif isinstance(node, (astroid.FunctionDef, astroid.ClassDef)):
                 defined_vars.add(node.name)
            elif isinstance(node, astroid.With):
                 for item in node.items:
                      if item[1] and isinstance(item[1], astroid.Name): defined_vars.add(item[1].name)
            # Comprehension 변수는 별도 스코프 가지므로 여기서 추가하지 않음 (필요시 수정)

    return defined_vars

def _add_target_names(target_node: astroid.NodeNG, defined_vars: Set[str]):
     """할당 또는 루프의 대상 노드에서 변수 이름을 추출하여 집합에 추가합니다."""
     if isinstance(target_node, astroid.Name):
          defined_vars.add(target_node.name)
     elif isinstance(target_node, (astroid.Tuple, astroid.List)):
          for elt in target_node.elts:
               _add_target_names(elt, defined_vars) # 재귀 호출