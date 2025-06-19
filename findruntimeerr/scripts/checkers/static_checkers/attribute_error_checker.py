import astroid
import sys
from checkers.base_checkers import BaseAstroidChecker

class StaticAttributeErrorChecker(BaseAstroidChecker):
    MSG_ID_PREFIX = 'E'; NAME = 'static-attribute-error'; node_types = (astroid.Attribute,)
    MSGS = {'0301': ("AttributeError: Attribute may not exist (Static)", 'attribute-error', '')}
    def check(self, node: astroid.Attribute):
        # --- 디버깅 로그 추가 ---
        print(f"DEBUG: Running {self.NAME} on node: {node.as_string()}", file=sys.stderr)
        try:
            # list()로 감싸서 StopIteration을 방지하는 것이 일반적
            value_inferred_list = list(node.value.infer(context=None))
            has_attribute = False
            none_error_reported = False
            possible_types = set()
            for inferred in value_inferred_list:
                if inferred is astroid.Uninferable:
                    possible_types.add("Uninferable")
                    continue
                if inferred is None:
                    none_error_reported = True
                    continue
                possible_types.add(type(inferred).__name__)
                if hasattr(inferred, 'getattr'):
                    try:
                        inferred.getattr(node.attrname)
                        has_attribute = True
                    except astroid.AttributeInferenceError:
                        pass
            if not has_attribute and not none_error_reported:
                types_str = ", ".join(sorted(list(set(pt for pt in possible_types if pt != "Uninferable"))))
                if types_str:
                    # --- 디버깅 로그 추가 ---
                    print(f"DEBUG: {self.NAME} FOUND an error for '{node.attrname}'", file=sys.stderr)
                    self.add_message(node, '0301', (types_str, node.attrname,))
        except astroid.InferenceError:
            pass
        except Exception as e:
            # StopIteration 같은 예외도 여기서 잡아서 로그 남기기
            print(f"ERROR in {self.NAME} for {repr(node)[:100]}...: {e}", file=sys.stderr)
            import traceback
            traceback.print_exc(file=sys.stderr)
