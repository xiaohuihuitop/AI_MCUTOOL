"""@brief AI:读取及写入KiCad公开S表达式文件，保留字符串与标识符的区别。"""
import json
import re


class Atom(str):
    """AI:不加引号的KiCad关键字或数字。"""


def parse(text):
    """@brief AI:解析一个S表达式。
    @param text UTF-8文本内容。
    @return 嵌套列表；引号字符串为str，其余词元为Atom。
    """
    stack = []
    root = None
    for token in re.findall(r'"(?:\\.|[^"\\])*"|[()]|[^\s()]+', text):
        if token == "(":
            node = []
            if stack:
                stack[-1].append(node)
            else:
                root = node
            stack.append(node)
        elif token == ")":
            stack.pop()
        else:
            value = json.loads(token) if token.startswith('"') else Atom(token)
            stack[-1].append(value)
    if stack:
        raise ValueError("S表达式括号未闭合")
    return root


def children(node, key):
    """@brief AI:获取指定关键字的直接子节点。
    @param node 父列表。
    @param key 关键字。
    @return 匹配的子节点列表。
    """
    return [v for v in node if isinstance(v, list) and v and v[0] == key]


def child(node, key):
    """@brief AI:获取唯一或首个指定子节点。
    @param node 父列表。
    @param key 关键字。
    @return 匹配节点；不存在时为None。
    """
    found = children(node, key)
    return found[0] if found else None


def dumps(node, indent=0):
    """@brief AI:序列化KiCad原生S表达式。
    @param node 列表、字符串或Atom。
    @param indent 当前缩进层级。
    @return 不带BOM的文本片段。
    """
    if not isinstance(node, list):
        return str(node) if isinstance(node, (Atom, int, float)) else json.dumps(node, ensure_ascii=False)
    if not any(isinstance(v, list) for v in node):
        return "(" + " ".join(dumps(v) for v in node) + ")"
    out = "("
    for i, value in enumerate(node):
        out += (("\n" + "  " * (indent + 1)) if isinstance(value, list) else (" " if i else "")) + dumps(value, indent + 1)
    return out + ")"
