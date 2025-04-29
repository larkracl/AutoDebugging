# utils.py
import astroid
import sys
from typing import Optional, Set, Union, List, Dict, Any

# --- 타입 추론 함수 ---
def get_type(node: astroid.NodeNG) -> Optional[str]:
    """astroid 노드의 타입을 추론합니다 (단일 타입 우선)."""
    try:
        inferred_list = list(node.infer())
        if not inferred_list or inferred_list[0] is astroid.Uninferable:
            if isinstance(node, astroid.Name): return 'Name'
            if isinstance(node, astroid.Call): return 'CallResult' # 호출 결과 타입 기본값
            # 다른 기본 타입 추정 추가 가능
            return None

        # 여러 추론 결과 중 첫 번째 (가장 가능성 높은) 타입 사용
        inferred = inferred_list[0]

        if isinstance(inferred, astroid.Const):
            return type(inferred.value).__name__
        elif isinstance(inferred, astroid.List):
            return "list"
        elif isinstance(inferred, astroid.Tuple):
            return "tuple"
        elif isinstance(inferred, astroid.Dict):
            return "dict"
        elif isinstance(inferred, astroid.Set): # Set 추가
             return "set"
        elif isinstance(inferred, astroid.FunctionDef):
            return "function"
        elif isinstance(inferred, astroid.ClassDef):
            return inferred.name
        elif isinstance(inferred, astroid.Instance):
             try:
                 # .pytype()은 클래스 이름을 포함한 완전한 타입 경로 반환 시도
                 # 예: 'mymodule.MyClass'
                 # 단순 이름만 필요하면 .name 사용 고려
                 return inferred.pytype()
             except (AttributeError, TypeError):
                 return inferred.name if hasattr(inferred, 'name') else 'Instance'
        elif isinstance(inferred, astroid.Module):
            return "module"
        elif isinstance(inferred, astroid.Name): # Name이 다시 추론된 경우
            if inferred.name in ('True', 'False'):
                return 'bool'
            # 재귀적 타입 추론 시도 (간단히)
            # return get_type(inferred) # 너무 깊어질 수 있으므로 주의
            return 'variable' # 또는 'unknown'
        elif isinstance(inferred, astroid.Lambda): # Lambda 추가
             return "function" # 람다도 함수 타입으로 간주
        elif isinstance(inferred, astroid.Call): # 함수/메서드 호출 결과
             # 호출된 함수의 반환 타입 추론 시도 (개선된 로직)
            try:
                 func_node = inferred.func
                 func_defs = list(func_node.infer())
                 if func_defs and func_defs[0] is not astroid.Uninferable:
                     actual_func = func_defs[0]
                     if isinstance(actual_func, astroid.FunctionDef):
                          # 반환 타입 힌트 확인
                          if actual_func.returns:
                               return_type_inferred = list(actual_func.returns.infer())
                               if return_type_inferred and return_type_inferred[0] is not astroid.Uninferable:
                                   # 추론된 반환 타입 반환 (더 정확)
                                   return get_type(return_type_inferred[0]) # 재귀 호출로 타입 이름 얻기
                          # return 문의 값 타입 추론 (더 복잡)
                          # for ret_node in actual_func.nodes_of_class(astroid.Return):
                          #     if ret_node.value: return get_type(ret_node.value)

                     # 내장 함수 처리
                     if hasattr(actual_func, 'name'):
                         if actual_func.name == 'len': return 'int'
                         if actual_func.name == 'str': return 'str'
                         # ... (다른 내장 함수) ...
                 return 'CallResult' # 일반 호출 결과
            except astroid.InferenceError:
                 return 'CallResult' # 추론 실패
    except astroid.InferenceError:
        return None
    except Exception as e:
        # 디버깅을 위해 에러 로깅
        print(f"Unexpected error in get_type for node {node!r}: {e}", file=sys.stderr)
        return None
    return None # 기본적으로 None 반환

# --- 타입 호환성 검사 ---
def is_compatible(type1: Optional[str], type2: Optional[str], op: str) -> bool:
    """두 타입이 주어진 연산에 대해 호환되는지 확인합니다."""
    if type1 is None or type2 is None or type1 == 'Unknown' or type2 == 'Unknown' or type1 == 'CallResult' or type2 == 'CallResult' or type1 == 'variable' or type2 == 'variable' or type1 == 'Name' or type2 == 'Name':
        # 추론 불가 또는 불확실한 타입은 일단 호환된다고 가정 (오탐 방지)
        return True

    if type1 == type2:
        return True

    numeric_types = ("int", "float", "complex", "bool") # bool도 숫자 연산 가능
    sequence_types = ("str", "list", "tuple")
    set_types = ("set", "frozenset")
    mapping_types = ("dict",)

    # 숫자 타입 간 연산
    if type1 in numeric_types and type2 in numeric_types:
        if op in ("+", "-", "*", "/", "//", "%", "**", "<", "<=", ">", ">=", "==", "!="):
            return True
        # 비트 연산 (int, bool)
        if type1 in ("int", "bool") and type2 in ("int", "bool") and op in ("&", "|", "^", "<<", ">>"):
            return True

    # 시퀀스 타입 연산
    if type1 in sequence_types and type2 in sequence_types and type1 == type2 and op == '+': # 같은 시퀀스끼리 +
        return True
    if type1 in sequence_types and type2 == 'int' and op == '*': # 시퀀스 * int
        return True
    if type1 == 'int' and type2 in sequence_types and op == '*': # int * 시퀀스
        return True

    # 문자열 포매팅 (간단히 % 만 확인)
    if type1 == "str" and op == '%':
        return True # 우변 타입은 더 자세히 봐야 함

    # Set 연산
    if type1 in set_types and type2 in set_types:
         if op in ("|", "&", "-", "^", "<=", "<", ">=", ">", "==", "!="): # issubset, issuperset 등
             return True

    # 멤버십 테스트 (in, not in) - 대부분 타입 가능
    if op in ("in", "not in"):
        # type2가 컨테이너 타입인지 확인하면 더 좋음 (list, tuple, dict, set, str)
        if type2 in sequence_types or type2 in set_types or type2 in mapping_types:
            return True
        # 다른 컨테이너 타입 추론 결과(예: 사용자 정의 클래스)도 고려 가능

    # TODO: 사용자 정의 클래스의 매직 메서드(__add__, __mul__ 등) 고려

    return False

# --- 정의된 변수 수집 ---
def collect_defined_variables(scope_node: Union[astroid.FunctionDef, astroid.Module, astroid.ClassDef, astroid.Lambda]) -> Set[str]:
    """주어진 스코프 내에서 정의된 변수/함수/클래스 이름을 수집합니다."""
    defined_vars: Set[str] = set()

    # 함수/람다 매개변수
    if isinstance(scope_node, (astroid.FunctionDef, astroid.Lambda)):
        try:
            args = scope_node.args
            for arg in args.args + args.posonlyargs + args.kwonlyargs:
                defined_vars.add(arg.name)
            if args.vararg: defined_vars.add(args.vararg)
            if args.kwarg: defined_vars.add(args.kwarg)
        except AttributeError: pass # lambda 등 args 없을 수 있음

    # 클래스 스코프: 메서드/클래스 변수 (간단히 이름만 추가)
    elif isinstance(scope_node, astroid.ClassDef):
         for node in scope_node.body:
              if isinstance(node, (astroid.FunctionDef, astroid.AssignName, astroid.AnnAssign)):
                   defined_vars.add(node.name if hasattr(node,'name') else node.target.name)


    # 스코프 본문 순회 (함수, 모듈, 클래스)
    if hasattr(scope_node, 'body'):
        current_scope_nodes = scope_node.body if isinstance(scope_node.body, list) else [scope_node.body]

        for node in current_scope_nodes:
            # 할당문의 타겟
            if isinstance(node, astroid.Assign):
                for target in node.targets:
                    if isinstance(target, astroid.Name): defined_vars.add(target.name)
                    elif isinstance(target, (astroid.Tuple, astroid.List)): # 튜플/리스트 언패킹 할당
                         for elt in target.elts:
                             if isinstance(elt, astroid.Name): defined_vars.add(elt.name)
            # For 루프 변수
            elif isinstance(node, astroid.For):
                 if isinstance(node.target, astroid.Name): defined_vars.add(node.target.name)
                 elif isinstance(node.target, (astroid.Tuple, astroid.List)): # 튜플/리스트 언패킹
                      for elt in node.target.elts:
                          if isinstance(elt, astroid.Name): defined_vars.add(elt.name)
            # 타입 힌트가 있는 할당
            elif isinstance(node, astroid.AnnAssign):
                 if isinstance(node.target, astroid.Name): defined_vars.add(node.target.name)
            # AugAssign (+= 등) - 변수가 이미 존재해야 함
            elif isinstance(node, astroid.AugAssign):
                 if isinstance(node.target, astroid.Name): defined_vars.add(node.target.name) # 이미 있어야 하지만 추가
            # Import 문
            elif isinstance(node, astroid.Import):
                 for alias in node.names: defined_vars.add(alias[1] or alias[0]) # as 이름 또는 원래 이름
            elif isinstance(node, astroid.ImportFrom):
                 for alias in node.names: defined_vars.add(alias[1] or alias[0])
            # 함수/클래스 정의 (해당 스코프 내 정의)
            elif isinstance(node, (astroid.FunctionDef, astroid.ClassDef)):
                 defined_vars.add(node.name)
            # With 문 변수 (as ...)
            elif isinstance(node, astroid.With):
                 for item in node.items:
                      if item[1] and isinstance(item[1], astroid.Name):
                           defined_vars.add(item[1].name)
            # Comprehension 변수 (간단 처리) - 별도 스코프 규칙 주의
            # elif isinstance(node, (astroid.ListComp, astroid.DictComp, astroid.SetComp, astroid.GeneratorExp)):
            #     for gen in node.generators:
            #         if isinstance(gen.target, astroid.Name): defined_vars.add(gen.target.name)

    return defined_vars