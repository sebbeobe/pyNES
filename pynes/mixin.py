# -*- coding: utf-8 -*-
import ast
from pynes.asm import *


def get_import(module_name, function_name):
    return ast.ImportFrom(
        module=module_name,
        names=[ast.alias(name=function_name, asname=None)],
        level=0)


def load_proxy(proxy):
    return ast.Name(id=proxy.name, ctx=ast.Load())


def call_proxy(var, func):
    return ast.Assign(
        targets=[ast.Name(id=var, ctx=ast.Store()),],
        value=ast.Call(func=ast.Name(id=func, ctx=ast.Load()), args=[], keywords=[], starargs=None, kwargs=None))


def get_node(obj):
    if type(obj).__name__ == 'InstructionProxy':
        obj = load_proxy(obj)
    return obj


def asm_nodes(func):
    def wrapper(*args, **kwargs):
        result = func(*args, **kwargs)
        if isinstance(result, ast.AST):
            return result
        instructions = result[::-1]
        left = get_node(instructions.pop())
        right = get_node(instructions.pop())
        binOp = ast.BinOp(left=left, op=ast.Add(), right=right)
        while len(instructions) > 0:
            binOp = ast.BinOp(left=binOp, op=ast.Add(), right=get_node(instructions.pop()))
        return binOp
    return wrapper


class AssignMixin(object):

    @asm_nodes
    def visit_Assign(self, node):
        self.generic_visit(node)

        if isinstance(node.value, ast.Call):
            # pynes.Game
            return node

        assert len(node.value) == len(node.targets)
        if len(node.value) == 1:
            value = node.value[0]
            target = node.targets[0]
            return [LDA, value, STA, target]

        return node

    @asm_nodes
    def visit_AugAssign(self, node):
        self.generic_visit(node)
        assert len(node.value) == 1
        value = node.value[0]
        target = node.target
        if isinstance(value, ast.Num) and value.n == 1:
            return [LDA, target, INC, STA, target]
        else:
            return [LDA, target, CLC, ADC, value, STA, target]

class StructMixin(object):

    def __init__(self, *args, **kwargs):
        self.module_lookup = {}
        self.names = {}

    def visit_ImportFrom(self, node):
        self.generic_visit(node)
        for m in node.names:
            if m.asname:
                self.module_lookup[m.asname] = '%s.%s' % (node.module, node.name)
            else:
                self.module_lookup[m.name] = '%s.%s' % (node.module, m.name)
        return node

    def visit_Module(self, node):
        node.body.insert(0, get_import('pynes.asm', '*'))
        node.body.insert(1, get_import('pynes.game', 'Game'))
        node.body.insert(2, call_proxy('game', 'Game'))
        ast.fix_missing_locations(node)
        self.generic_visit(node)

        for i, n in enumerate(node.body):
            if isinstance(n, ast.Expr):
                node.body[i] = ast.Call(
                    func=ast.Attribute(value=ast.Name(id='game', ctx=ast.Load()), attr='add_chunk', ctx=ast.Load()),
                    args=[n.value], keywords=[], starargs=None, kwargs=None)
            elif isinstance(n, ast.BinOp):
                node.body[i] = ast.Call(
                    func=ast.Attribute(value=ast.Name(id='game', ctx=ast.Load()), attr='add_chunk', ctx=ast.Load()),
                    args=[n], keywords=[], starargs=None, kwargs=None)

        ast.fix_missing_locations(node)

        # import astpp
        # print astpp.dump(node)
        return node

    def visit_FunctionDef(self, node):
        self.generic_visit(node)
        node.decorator_list.insert(0,
            ast.Attribute(value=ast.Name(id='game', ctx=ast.Load()), attr='function', ctx=ast.Load())
        )
        return node

    def is_valid_name(self, name):
        return name != 'pynes.lib.asm_def'

    def visit_Name(self, node):
        self.generic_visit(node)
        if self.is_valid_name(self.module_lookup.get(node.id, False)):
            self.names[node.id] = 'a'
        return node


class LogicOperationMixin(object):

    def visit_Call(self, node):
        if node.func.id == 'press_start':
            return None
        self.generic_visit(node)
        return node

    def visit_Mod(self, node):
        return [AND]


class MathOperationMixin(object):

    def visit_Expr(self, node):
        self.generic_visit(node)
        if hasattr(node, 'value'):
            return node
        return None

        return ast.Expr(value=ast.Assign(
            targets=[ast.Name(id='expr', ctx=ast.Store())],
            value=node))

    def visit_Add(self, node):
        return [CLC, ADC]

    def visit_Sub(self, node):
        return [SEC, SBC]

    def visit_Mult(self, node):
        return [ASL]

    def visit_Num(self, node):
        return [node]

    @asm_nodes
    def visit_BinOp(self, node):
        self.generic_visit(node)
        instructions = []
        if isinstance(node.left, ast.BinOp):
            next = node.left
            while isinstance(next, ast.BinOp):
                instructions.append(next.right)
                next = next.left
            instructions.reverse()
        else:
            instructions += node.left

        if ASL not in node.op:
            instructions += node.op + node.right
        else:
            assert len(node.right) == 1
            right = node.right[0]
            if isinstance(right, ast.Num) and right.n % 2 == 0:
                node.op *= right.n / 2
                instructions += node.op

        return [LDA] + instructions
