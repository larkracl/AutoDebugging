import astroid
import csv
import sys
from typing import Optional, Union

def parse_python_code(file_path: str):
    """
    주어진 Python 파일 경로를 astroid를 사용하여 파싱하고, AST 정보를 CSV 형식으로 반환합니다.

    Args:
        file_path: 파싱할 Python 파일 경로.

    Returns:
        list[list]: CSV 데이터 (행 리스트).
    """
    try:
        tree = astroid.MANAGER.ast_from_file(file_path)
    except astroid.AstroidSyntaxError as e:
        print(f"Error: {e}")
        return [["Error", str(e)]]
    except FileNotFoundError:
        print("Error File Not Found")
        return [["Error", "File Not Found"]]

    csv_data = []
    csv_data.append(["Node Type", "Attributes", "Inferred Type", "Parent Node Type", "Parent Attributes"])  # 헤더 변경

    def traverse_ast(node: astroid.NodeNG, parent_info: Optional[list] = None):

        node_info = [type(node).__name__]
        node_attributes = []

        if hasattr(node, 'name'):
            node_attributes.append(f"name: {node.name}")
        if hasattr(node, 'op'):
            node_attributes.append(f"op: {node.op}")
        if hasattr(node, 'value'):
            if isinstance(node.value, astroid.Const):
                node_attributes.append(f"value: {node.value.value}")  # 상수 값
            elif isinstance(node.value, astroid.NodeNG):
                node_attributes.append(f"value: ({type(node.value).__name__})")
            else:
                node_attributes.append(f"value: {node.value}")
        if hasattr(node, 'lineno'):
            node_attributes.append(f"lineno: {node.lineno}")
        if hasattr(node, 'col_offset'):
            node_attributes.append(f"col_offset: {node.col_offset}")

        node_info.append(", ".join(node_attributes))

        # 타입 추론 정보 추가
        try:
            inferred_types = [t.name for t in node.infer()]  # 가능한 모든 타입 추론
            node_info.append(", ".join(inferred_types))
        except astroid.InferenceError:
            node_info.append("InferenceError")
        except Exception:
            node_info.append("Unknown")

        if parent_info:
            node_info.extend(parent_info)
        else:
            node_info.extend(["None", "None"])

        csv_data.append(node_info)
        parent_info = [type(node).__name__, ", ".join(node_attributes)]

        for child in node.get_children():
            traverse_ast(child, parent_info)

    traverse_ast(tree)
    return csv_data

def write_csv(csv_data: list, output_file: str):
    """
    CSV 데이터를 파일에 씁니다.
    """
    with open(output_file, 'w', newline='', encoding='utf-8') as csvfile:
        csv_writer = csv.writer(csvfile)
        csv_writer.writerows(csv_data)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python parse_to_csv.py <python_file_path> [output_csv_path]")
        sys.exit(1)

    python_file = sys.argv[1]
    output_csv = sys.argv[2] if len(sys.argv) > 2 else "output.csv"

    csv_data = parse_python_code(python_file)
    if csv_data:
        write_csv(csv_data, output_csv)
        print(f"AST information saved to '{output_csv}'")