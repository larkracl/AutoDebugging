# utils.py
import astroid
from typing import Optional, Set

def get_type(node: astroid.NodeNG) -> Optional[str]:
    """astroid 노드의 타입을 추론합니다."""
    try:
        for inferred in node.infer():
            if inferred is astroid.Uninferable:
                return None

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
                return inferred.name
            elif isinstance(inferred, astroid.Instance):
                return inferred.name
            elif isinstance(inferred, astroid.Module):
                return "module"
            elif isinstance(inferred, astroid.Name):  # 변수
                if inferred.name in ('True', 'False'):
                    return 'bool'
    except astroid.InferenceError:
        return None
    return None

def is_compatible(type1: Optional[str], type2: Optional[str], op: str) -> bool:
    """두 타입이 주어진 연산에 대해 호환되는지 확인합니다."""
    if type1 is None or type2 is None:  # 타입을 추론할 수 없는 경우
        return True  # 일단 호환된다고 가정 (더 정교한 분석 필요)

    if type1 == type2:
        return True

    # 숫자 타입
    if type1 in ("int", "float") and type2 in ("int", "float"):
        if op in ("+", "-", "*", "/", "//", "%", "**"):
            return True

    # 문자열
    if type1 == "str" and type2 == "str" and op == '+':
        return True
    if type1 == 'str' and type2 == 'int' and op == '*':
        return True

    # 리스트
    if type1 == 'list' and type2 == 'list' and op == '+':
        return True
    if type1 == 'list' and type2 == 'int' and op == '*':
        return True

    return False

def collect_defined_variables(func_node: astroid.FunctionDef) -> Set[str]:
    """함수 내에서 정의된 변수 이름을 수집합니다."""
    defined_vars: Set[str] = set()
    # 함수 매개변수
    for arg in func_node.args.args + func_node.args.posonlyargs + func_node.args.kwonlyargs:
        defined_vars.add(arg.name)
    if func_node.args.vararg:
        defined_vars.add(func_node.args.vararg)
    if func_node.args.kwarg:
        defined_vars.add(func_node.args.kwarg)

    # 함수 본문 내 할당문
    for node in func_node.body:
        if isinstance(node, astroid.Assign):
            for target in node.targets:
                if isinstance(target, astroid.Name):
                    defined_vars.add(target.name)
    return defined_vars