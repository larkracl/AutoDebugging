# scripts/checkers/static_checkers/attribute_error_checker.py
import astroid
import sys

# *** 수정된 import 경로 ***
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
            value_inferred_list = list(node.expr.infer(context=None))
            if not value_inferred_list: return
            has_attribute = False; possible_types = []; none_error_reported = False
            for inferred in value_inferred_list:
                if inferred is astroid.Uninferable: possible_types.append("Uninferable"); continue
                current_type_name = getattr(inferred, 'qname', getattr(inferred, 'name', type(inferred).__name__))
                if isinstance(inferred, astroid.Const) and inferred.value is None:
                    if not none_error_reported:
                        print(f"DEBUG: {self.NAME} FOUND a NoneType error for '{node.attrname}'", file=sys.stderr)
                        self.add_message(node.attrname, '0402', (node.attrname,)); none_error_reported = True
                    continue
                possible_types.append(current_type_name)
                try: inferred.getattr(node.attrname); has_attribute = True; break
                except (astroid.NotFoundError, AttributeError): pass
            if not has_attribute and not none_error_reported:
                types_str = ", ".join(sorted(list(set(pt for pt in possible_types if pt != "Uninferable"))))
                if types_str:
                    print(f"DEBUG: {self.NAME} FOUND a no-member error for '{node.attrname}' on types '{types_str}'", file=sys.stderr)
                    self.add_message(node.attrname, '0401', (types_str, node.attrname,))
        except astroid.InferenceError: pass
        except Exception as e: print(f"ERROR in {self.NAME} for {repr(node)[:100]}...: {e}", file=sys.stderr)