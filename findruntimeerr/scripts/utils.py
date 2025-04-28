# utils.py
import astroid
from typing import Optional, Set

def get_type(node: astroid.NodeNG) -> Optional[str]:
    """astroid 노드의 타입을 추론합니다."""
    try:
        inferred_list = list(node.infer())
        if not inferred_list or inferred_list[0] is astroid.Uninferable:
            # 추론 실패 시, 노드 자체의 타입 반환 시도
            if isinstance(node, astroid.Name): return 'Name' # 변수명 자체
            if isinstance(node, astroid.Call): return 'Call' # 함수 호출 자체
            # ... 다른 노드 타입 추가 가능
            return None

        inferred = inferred_list[0] # 첫 번째 추론 결과 사용 (가장 가능성 높은 것)

        if isinstance(inferred, astroid.Const):
            return type(inferred.value).__name__
        elif isinstance(inferred, astroid.List):
            return "list"
        elif isinstance(inferred, astroid.Tuple):
            return "tuple"
        elif isinstance(inferred, astroid.Dict):
            return "dict"
        elif isinstance(inferred, astroid.FunctionDef):
            return "function"
        elif isinstance(inferred, astroid.ClassDef):
            return inferred.name # 클래스 이름
        elif isinstance(inferred, astroid.Instance):
             # 인스턴스의 클래스 이름 반환
             try:
                 return inferred.pytype()
             except (AttributeError, TypeError): # pytype() 없을 수 있음
                 return inferred.name if hasattr(inferred, 'name') else 'Instance'
        elif isinstance(inferred, astroid.Module):
            return "module"
        elif isinstance(inferred, astroid.Name):
            if inferred.name in ('True', 'False'):
                return 'bool'
            # Name 노드가 다시 추론되는 경우, 실제 타입 대신 이름 반환은 혼란 유발 가능
            # return inferred.name # 이 부분은 제거하거나 주의해서 사용
        elif isinstance(inferred, astroid.Call): # 함수 호출 결과 타입 추론 (개선)
            try:
                 # 호출된 함수의 반환 타입 추론 시도
                 func_defs = list(inferred.func.infer())
                 if func_defs and func_defs[0] is not astroid.Uninferable and isinstance(func_defs[0], astroid.FunctionDef):
                     # FunctionDef에서 반환 타입 힌트나 return문의 값 추론 (복잡)
                     # 여기서는 간단히 내장 함수 일부만 처리
                     if func_defs[0].name == 'len': return 'int'
                     if func_defs[0].name == 'str': return 'str'
                     if func_defs[0].name == 'int': return 'int'
                     if func_defs[0].name == 'float': return 'float'
                     # TODO: 더 많은 내장/사용자 정의 함수 반환 타입 추론
                 return 'CallResult' # 일반적인 호출 결과 타입
            except astroid.InferenceError:
                 return 'CallResult'
    except astroid.InferenceError:
        return None # 추론 중 오류 발생 시
    except Exception as e:
        print(f"Unexpected error in get_type for node {node!r}: {e}", file=sys.stderr)
        return None # 예상치 못한 오류 발생 시
    return None # 기본값

def is_compatible(type1: Optional[str], type2: Optional[str], op: str) -> bool:
    """두 타입이 주어진 연산에 대해 호환되는지 확인합니다."""
    if type1 is None or type2 is None:
        return True # 추론 불가 시 호환 간주

    if type1 == type2:
        return True

    numeric_types = ("int", "float", "complex") # complex 추가
    string_type = "str"
    list_type = "list"
    tuple_type = "tuple"
    # set_type = "set" # set 연산 추가 가능
    # dict_type = "dict" # dict 연산 추가 가능

    # 숫자 타입 간 연산
    if type1 in numeric_types and type2 in numeric_types:
        if op in ("+", "-", "*", "/", "//", "%", "**"):
            return True
        if op in ("<", "<=", ">", ">=", "==", "!="): # 비교 연산
            return True

    # 문자열 연산
    if type1 == string_type and type2 == string_type and op == '+':
        return True
    if type1 == string_type and type2 == 'int' and op == '*': # str * int
        return True
    if type1 == 'int' and type2 == string_type and op == '*': # int * str
        return True
    if type1 == string_type and type2 == string_type and op in ("==", "!=", "<", "<=", ">", ">="): # 문자열 비교
        return True


    # 리스트 연산
    if type1 == list_type and type2 == list_type and op == '+':
        return True
    if type1 == list_type and type2 == 'int' and op == '*': # list * int
        return True
    if type1 == 'int' and type2 == list_type and op == '*': # int * list
        return True

    # 튜플 연산
    if type1 == tuple_type and type2 == tuple_type and op == '+':
        return True
    if type1 == tuple_type and type2 == 'int' and op == '*': # tuple * int
        return True
    if type1 == 'int' and type2 == tuple_type and op == '*': # int * tuple
        return True


    # TODO: 더 많은 타입 조합과 연산자 처리 (예: set 연산자 |, &, -, ^)
    # TODO: 사용자 정의 클래스 __add__, __mul__ 등 매직 메서드 고려

    return False

def collect_defined_variables(func_node: astroid.FunctionDef) -> Set[str]:
    """함수 내에서 정의된 변수 이름을 수집합니다."""
    defined_vars: Set[str] = set()
    # 함수 매개변수
    try: # Arguments 객체가 없을 수도 있음 (lambda 등)
        args = func_node.args
        for arg in args.args + args.posonlyargs + args.kwonlyargs:
            defined_vars.add(arg.name)
        if args.vararg:
            defined_vars.add(args.vararg)
        if args.kwarg:
            defined_vars.add(args.kwarg)
    except AttributeError:
        pass # Arguments 객체 없으면 무시

    # 함수 본문 내 할당문 (단순 할당만 고려)
    for node in func_node.body:
        if isinstance(node, astroid.Assign):
            for target in node.targets:
                if isinstance(target, astroid.Name):
                    defined_vars.add(target.name)
        # TODO: AugAssign (+=), AnnAssign (type hints), For 루프 변수 등 추가 고려
        elif isinstance(node, astroid.For): # For 루프 변수
             if isinstance(node.target, astroid.Name):
                 defined_vars.add(node.target.name)
        elif isinstance(node, astroid.AnnAssign): # 타입 힌트 할당
             if isinstance(node.target, astroid.Name):
                 defined_vars.add(node.target.name)
        elif isinstance(node, astroid.AugAssign): # += 등
             if isinstance(node.target, astroid.Name):
                 defined_vars.add(node.target.name) # 이미 있어야 하지만 추가

    return defined_vars