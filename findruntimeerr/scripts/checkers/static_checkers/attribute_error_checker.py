# scripts/checkers/static_checkers/attribute_error_checker.py
import astroid
import sys
import traceback

from checkers.base_checkers import BaseAstroidChecker

class StaticAttributeErrorChecker(BaseAstroidChecker):
    MSG_ID_PREFIX = 'E'; NAME = 'static-attribute-error'; node_types = (astroid.Attribute,)
    MSGS = {
        '0401': ("AttributeError: Object of type '%s' has no attribute '%s' (Static)", 'no-member', ''),
        '0402': ("AttributeError: 'NoneType' object has no attribute '%s' (Static)", 'none-attr-error', '')
    }

    def check(self, node: astroid.Attribute):
        # print(f"DEBUG: Running {self.NAME} on node: {node.as_string()}", file=sys.stderr)

        try:
            # *** 수정 1: node.value -> node.expr ***
            # Attribute 노드에서 속성이 접근되는 객체(왼쪽 부분)는 .expr 속성입니다.
            inferred_values = list(node.expr.infer(context=None))

            if not inferred_values: # 타입을 전혀 추론할 수 없으면 검사 불가
                # print(f"DEBUG: Cannot infer type for: {node.expr.as_string()}", file=sys.stderr)
                return

            has_attribute = False
            none_error_reported = False
            possible_types = []

            for inferred in inferred_values:
                if inferred is astroid.Uninferable:
                    possible_types.append("Uninferable")
                    continue

                # NoneType 체크
                if isinstance(inferred, astroid.Const) and inferred.value is None:
                    if not none_error_reported:
                        print(f"DEBUG: {self.NAME} FOUND a NoneType error for '{node.attrname}'", file=sys.stderr)
                        # *** 수정 2: node.attrname -> node ***
                        # add_message에는 위치 정보를 위해 전체 Attribute 노드를 전달해야 합니다.
                        self.add_message(node, '0402', (node.attrname,))
                        none_error_reported = True
                    # None이면 더 이상 다른 타입을 체크할 필요가 없습니다 (일단).
                    # 만약 여러 추론 결과 중 하나라도 None이면 오류 보고 후 종료 가능
                    # return # 더 엄격하게 하려면 여기서 종료
                    continue

                # StaticAttributeErrorChecker의 check 메서드 내부
                current_type_name_obj = getattr(inferred, 'qname', getattr(inferred, 'name', type(inferred).__name__))
                # 항상 문자열로 변환 보장
                current_type_name = str(current_type_name_obj)
                possible_types.append(current_type_name)

                try:
                    # inferred 객체(추론된 타입)에서 속성을 찾아봅니다.
                    inferred.getattr(node.attrname)
                    # 성공하면 속성이 있는 것이므로 더 이상 검사할 필요 없음
                    has_attribute = True
                    break
                except (astroid.NotFoundError, AttributeError):
                    # 해당 타입에 속성이 없음. 계속 다른 추론된 타입 확인.
                    pass

            # 모든 추론된 타입에서 속성을 찾지 못했고, None 오류도 아니었다면
            if not has_attribute and not none_error_reported:
                # Uninferable을 제외하고 유효한 타입 이름들만 조합하여 메시지 생성
                types_str = ", ".join(sorted(list(set(pt for pt in possible_types if pt != "Uninferable"))))
                if types_str: # 타입 정보가 있을 때만 보고
                    print(f"DEBUG: {self.NAME} FOUND a no-member error for '{node.attrname}' on types '{types_str}'", file=sys.stderr)
                    # *** 수정 3: node.attrname -> node ***
                    # add_message에는 위치 정보를 위해 전체 Attribute 노드를 전달해야 합니다.
                    self.add_message(node, '0401', (types_str, node.attrname,))

        except astroid.InferenceError:
            # 타입 추론 과정 자체에서 발생하는 오류는 일반적이므로 조용히 넘어갑니다.
            pass
        except Exception as e:
            # StopIteration 등 다른 예외 발생 시 로깅
            print(f"ERROR in {self.NAME} for {repr(node)[:100]}...: {e}", file=sys.stderr)
            traceback.print_exc(file=sys.stderr)