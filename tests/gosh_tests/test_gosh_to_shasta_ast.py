#!/usr/bin/env python3
"""Minimal tests for the gosh (shfmt) JSON to shasta bridge."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT_DIR))

from shasta.ast_node import (
    AArgChar,
    AndNode,
    ArgChar,
    ArithForNode,
    ArithNode,
    AssignNode,
    AstNode,
    BackgroundNode,
    BArgChar,
    CArgChar,
    CaseNode,
    CommandNode,
    CondNode,
    CondType,
    CoprocNode,
    DefunNode,
    DupRedirNode,
    FileRedirNode,
    ForNode,
    GroupNode,
    HeredocRedirNode,
    IfNode,
    NotNode,
    OrNode,
    PArgChar,
    PipeNode,
    QArgChar,
    RedirNode,
    SelectNode,
    SingleArgRedirNode,
    SubshellNode,
    TimeNode,
    VArgChar,
    WhileNode,
    ast_node_to_untyped_deep,
)
from shasta.gosh_to_shasta_ast import to_ast_node, to_ast_nodes


def argchars(text: str) -> list[ArgChar]:
    return [CArgChar(ord(ch)) for ch in text]


def cond_term(text: str, line: int = -1) -> CondNode:
    return CondNode(
        line_number=line,
        cond_type=CondType.COND_TERM.value,
        op=argchars(text),
        left=None,
        right=None,
        invert_return=False,
    )


def cond_unary(op: str, inner: CondNode, line: int = -1) -> CondNode:
    return CondNode(
        line_number=line,
        cond_type=CondType.COND_UNARY.value,
        op=argchars(op),
        left=inner,
        right=None,
        invert_return=False,
    )


def cond_binary(op: str, left: CondNode, right: CondNode, line: int = -1) -> CondNode:
    return CondNode(
        line_number=line,
        cond_type=CondType.COND_BINARY.value,
        op=argchars(op),
        left=left,
        right=right,
        invert_return=False,
    )


def cond_and(left: CondNode, right: CondNode, line: int = -1) -> CondNode:
    return CondNode(
        line_number=line,
        cond_type=CondType.COND_AND.value,
        op=None,
        left=left,
        right=right,
        invert_return=False,
    )


def cond_or(left: CondNode, right: CondNode, line: int = -1) -> CondNode:
    return CondNode(
        line_number=line,
        cond_type=CondType.COND_OR.value,
        op=None,
        left=left,
        right=right,
        invert_return=False,
    )


def word_json(text: str) -> dict[str, object]:
    return {"Parts": [{"Type": "Lit", "Value": text}]}


def lit_json(text: str) -> dict[str, object]:
    return {"Type": "Lit", "Value": text}


def call_json(
    args: list[dict[str, object]], assigns: list[dict[str, object]] | None = None
) -> dict[str, object]:
    return {
        "Type": "CallExpr",
        "Assigns": assigns or [],
        "Args": args,
    }


def stmt_json(cmd: dict[str, object], **kwargs: object) -> dict[str, object]:
    out: dict[str, object] = {"Cmd": cmd}
    out.update(kwargs)
    return out


def assert_shasta_equal(actual: object, expected: object) -> None:
    assert ast_node_to_untyped_deep(actual) == ast_node_to_untyped_deep(expected)


def shfmt_to_shasta_nodes(script: str) -> list[AstNode]:
    script_text = (
        script if script.endswith("\n") else f"{script}\n"
    )  # Add trailing newline if missing
    with tempfile.NamedTemporaryFile("wb", suffix=".sh", delete=False) as handle:
        path = handle.name
        handle.write(script_text.encode("utf-8"))
    try:
        proc = subprocess.run(
            ["shfmt", "--to-json", "-filename", path],
            input=script_text.encode("utf-8"),
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("shfmt not found on PATH") from exc
    finally:
        os.unlink(path)
    payload = json.loads(proc.stdout.decode("utf-8"))
    return to_ast_nodes(payload)


def test_call_expr_with_assign() -> None:
    # A=1 echo
    shfmt_node = call_json(
        args=[word_json("echo")],
        assigns=[{"Name": lit_json("A"), "Value": word_json("1")}],
    )
    expected = CommandNode(
        line_number=-1,
        assignments=[AssignNode("A", argchars("1"))],
        arguments=[argchars("echo")],
        redir_list=[],
    )

    actual = to_ast_node(shfmt_node)

    assert_shasta_equal(actual, expected)


def test_binary_cmd_ops() -> None:
    # true && false
    left = stmt_json(call_json([word_json("true")]))
    right = stmt_json(call_json([word_json("false")]))

    shfmt_and = {
        "Type": "BinaryCmd",
        "Op": 11,
        "X": left,
        "Y": right,
    }
    expected_and = AndNode(
        left_operand=CommandNode(-1, [], [argchars("true")], []),
        right_operand=CommandNode(-1, [], [argchars("false")], []),
        no_braces=True,
    )

    actual = to_ast_node(shfmt_and)

    assert_shasta_equal(actual, expected_and)

    # true || false
    shfmt_or = {
        "Type": "BinaryCmd",
        "Op": 12,
        "X": left,
        "Y": right,
    }
    expected_or = OrNode(
        left_operand=CommandNode(-1, [], [argchars("true")], []),
        right_operand=CommandNode(-1, [], [argchars("false")], []),
        no_braces=True,
    )

    actual = to_ast_node(shfmt_or)

    assert_shasta_equal(actual, expected_or)


def test_pipe_all_injects_dup() -> None:
    # echo hi |& cat
    left = stmt_json(call_json([word_json("echo")]))
    right = stmt_json(call_json([word_json("cat")]))
    shfmt_node = {
        "Type": "BinaryCmd",
        "Op": 14,
        "X": left,
        "Y": right,
    }
    expected = PipeNode(
        is_background=False,
        items=[
            CommandNode(
                -1,
                [],
                [argchars("echo")],
                [DupRedirNode("ToFD", ("fixed", 2), ("fixed", 1), move=False)],
            ),
            CommandNode(-1, [], [argchars("cat")], []),
        ],
    )

    actual = to_ast_node(shfmt_node)

    assert_shasta_equal(actual, expected)


def test_if_and_while_until() -> None:
    # if true; then echo hi; else false; fi
    cond_stmt = stmt_json(call_json([word_json("true")]))
    then_stmt = stmt_json(call_json([word_json("echo")]))
    else_stmt = stmt_json(call_json([word_json("false")]))
    shfmt_if = {
        "Type": "IfClause",
        "Cond": [cond_stmt],
        "Then": [then_stmt],
        "Else": {"Cond": [], "Then": [else_stmt]},
    }
    expected_if = IfNode(
        cond=CommandNode(-1, [], [argchars("true")], []),
        then_b=CommandNode(-1, [], [argchars("echo")], []),
        else_b=CommandNode(-1, [], [argchars("false")], []),
    )

    actual = to_ast_node(shfmt_if)

    assert_shasta_equal(actual, expected_if)

    # while true; do echo hi; done
    shfmt_while = {
        "Type": "WhileClause",
        "Cond": [cond_stmt],
        "Do": [then_stmt],
        "Until": True,
    }
    expected_while = WhileNode(
        test=NotNode(CommandNode(-1, [], [argchars("true")], []), no_braces=True),
        body=CommandNode(-1, [], [argchars("echo")], []),
    )

    actual = to_ast_node(shfmt_while)

    assert_shasta_equal(actual, expected_while)


def test_for_clause_variants() -> None:
    # for i in a b; do echo hi; done
    word_iter = {
        "Type": "WordIter",
        "Name": lit_json("i"),
        "Items": [word_json("a"), word_json("b")],
    }
    shfmt_for = {
        "Type": "ForClause",
        "Loop": word_iter,
        "Do": [stmt_json(call_json([word_json("echo")]))],
    }
    expected_for = ForNode(
        line_number=-1,
        argument=[argchars("a"), argchars("b")],
        body=CommandNode(-1, [], [argchars("echo")], []),
        variable=argchars("i"),
    )

    actual = to_ast_node(shfmt_for)

    assert_shasta_equal(actual, expected_for)

    # for i select a b; do echo hi; done
    shfmt_select = {
        "Type": "ForClause",
        "Loop": word_iter,
        "Select": True,
        "Do": [stmt_json(call_json([word_json("echo")]))],
    }
    expected_select = SelectNode(
        line_number=-1,
        variable=argchars("i"),
        body=CommandNode(-1, [], [argchars("echo")], []),
        map_list=[argchars("a"), argchars("b")],
    )

    actual = to_ast_node(shfmt_select)

    assert_shasta_equal(actual, expected_select)

    # for ((i=0; i<2; i++)); do echo hi; done
    cstyle = {
        "Type": "CStyleLoop",
        "Init": {"Type": "Word", "Parts": [lit_json("i=0")]},
        "Cond": {"Type": "Word", "Parts": [lit_json("i<2")]},
        "Post": {"Type": "Word", "Parts": [lit_json("i++")]},
    }
    shfmt_cstyle = {
        "Type": "ForClause",
        "Loop": cstyle,
        "Do": [stmt_json(call_json([word_json("echo")]))],
    }
    expected_cstyle = ArithForNode(
        line_number=-1,
        init=[argchars("i=0")],
        cond=[argchars("i<2")],
        step=[argchars("i++")],
        action=CommandNode(-1, [], [argchars("echo")], []),
    )

    actual = to_ast_node(shfmt_cstyle)

    assert_shasta_equal(actual, expected_cstyle)


def test_case_clause_fallthrough() -> None:
    # case x in a) echo hi ;& b) echo bye ;; esac
    case_item = {
        "Patterns": [word_json("a")],
        "Stmts": [stmt_json(call_json([word_json("echo")]))],
        "Op": 36,
    }
    shfmt_node = {
        "Type": "CaseClause",
        "Word": word_json("x"),
        "Items": [case_item],
    }
    expected = CaseNode(
        line_number=None,
        argument=argchars("x"),
        cases=[
            {
                "cpattern": [argchars("a")],
                "cbody": CommandNode(-1, [], [argchars("echo")], []),
                "fallthrough": True,
            }
        ],
    )

    actual = to_ast_node(shfmt_node)

    assert_shasta_equal(actual, expected)


def test_redirection_variants() -> None:
    # echo out > out 2>> err <<EOF < in <> inout
    shfmt_stmt = stmt_json(
        call_json([word_json("echo")]),
        Redirs=[
            {"Op": 63, "Word": word_json("out")},
            {"Op": 65, "Word": word_json("in")},
            {"Op": 71, "Word": word_json("EOF"), "Hdoc": word_json("body")},
            {"Op": 73, "Word": word_json("data")},
            {"Op": 67, "Word": word_json("1")},
            {"Op": 68, "Word": word_json("-")},
            {"Op": 74, "Word": word_json("out")},
        ],
    )
    expected = CommandNode(
        -1,
        [],
        [argchars("echo")],
        [
            FileRedirNode("To", ("fixed", 1), argchars("out")),
            FileRedirNode("From", ("fixed", 0), argchars("in")),
            HeredocRedirNode("XHere", ("fixed", 0), argchars("body"), False, "EOF"),
            FileRedirNode("ReadingString", ("fixed", 0), argchars("data")),
            DupRedirNode("FromFD", ("fixed", 0), ("fixed", 1), move=False),
            SingleArgRedirNode("CloseThis", ("fixed", 1)),
            SingleArgRedirNode("ErrAndOut", ("var", argchars("out"))),
        ],
    )

    actual = to_ast_node(shfmt_stmt)

    assert_shasta_equal(actual, expected)


def test_word_parts_and_param_exp() -> None:
    # echo hi there "you" ${VAR:-fallback} $(echo) $((1+2)) <(echo) ?(*.py) {a,b}
    shfmt_word: dict[str, object] = {
        "Parts": [
            {"Type": "Lit", "Value": "hi"},
            {"Type": "SglQuoted", "Value": "there"},
            {"Type": "DblQuoted", "Parts": [{"Type": "Lit", "Value": "you"}]},
            {
                "Type": "ParamExp",
                "Param": lit_json("VAR"),
                "Exp": {"Op": 84, "Word": word_json("fallback")},
            },
            {"Type": "CmdSubst", "Stmts": [stmt_json(call_json([word_json("echo")]))]},
            {"Type": "ArithmExp", "X": {"Type": "Word", "Parts": [lit_json("1+2")]}},
            {
                "Type": "ProcSubst",
                "Op": 78,
                "Stmts": [stmt_json(call_json([word_json("echo")]))],
            },
            {"Type": "ExtGlob", "Op": 139, "Pattern": lit_json("*.py")},
            {
                "Type": "BraceExp",
                "Elems": [word_json("a"), word_json("b")],
                "Sequence": False,
            },
        ]
    }

    shfmt_node = call_json([shfmt_word])
    expected = CommandNode(
        -1,
        [],
        [
            argchars("hi")
            + [QArgChar(argchars("there"))]
            + [QArgChar(argchars("you"))]
            + [VArgChar("Minus", True, "VAR", argchars("fallback"))]
            + [BArgChar(CommandNode(-1, [], [argchars("echo")], []))]
            + [AArgChar(argchars("1+2"))]
            + [PArgChar("<(", CommandNode(-1, [], [argchars("echo")], []))]
            + argchars("?(*.py)")
            + argchars("{a,b}")
        ],
        [],
    )

    actual = to_ast_node(shfmt_node)

    assert_shasta_equal(actual, expected)


def test_param_exp_names_fallback() -> None:
    # echo ${!arr*}
    shfmt_word: dict[str, object] = {
        "Parts": [{"Type": "ParamExp", "Param": lit_json("arr"), "Names": 43}]
    }
    shfmt_node = call_json([shfmt_word])
    expected = CommandNode(
        -1,
        [],
        [argchars("${!arr*}")],
        [],
    )

    actual = to_ast_node(shfmt_node)

    assert_shasta_equal(actual, expected)


def test_test_clause_binary() -> None:
    # [[ a -eq b ]]
    shfmt_node = {
        "Type": "TestClause",
        "X": {
            "Type": "BinaryTest",
            "Op": 133,
            "X": {"Type": "Word", "Parts": [lit_json("a")]},
            "Y": {"Type": "Word", "Parts": [lit_json("b")]},
        },
    }
    expected = cond_binary("-eq", cond_term("a"), cond_term("b"))

    actual = to_ast_node(shfmt_node)

    assert_shasta_equal(actual, expected)


def test_file_to_nodes() -> None:
    shfmt_file = {
        "Type": "File",
        "Stmts": [stmt_json(call_json([word_json("echo")]))],
    }
    expected = [CommandNode(-1, [], [argchars("echo")], [])]

    actual = to_ast_nodes(shfmt_file)

    assert_shasta_equal(actual, expected)


def test_shfmt_script_simple_call() -> None:
    script = "echo hi"
    expected = [CommandNode(1, [], [argchars("echo"), argchars("hi")], [])]

    actual = shfmt_to_shasta_nodes(script)

    assert_shasta_equal(actual, expected)


def test_shfmt_script_escape_param() -> None:
    script = "echo $HOME\necho \\$HOME"
    expected = [
        CommandNode(
            1,
            [],
            [argchars("echo"), [VArgChar("Normal", False, "HOME", [])]],
            [],
        ),
        CommandNode(2, [], [argchars("echo"), argchars("\\$HOME")], []),
    ]

    actual = shfmt_to_shasta_nodes(script)

    assert_shasta_equal(actual, expected)


def test_shfmt_script_escape_glob_literal() -> None:
    script = "echo *\necho \\*"
    expected = [
        CommandNode(1, [], [argchars("echo"), argchars("*")], []),
        CommandNode(2, [], [argchars("echo"), argchars("\\*")], []),
    ]

    actual = shfmt_to_shasta_nodes(script)

    assert_shasta_equal(actual, expected)


def test_shfmt_script_pipe_all() -> None:
    script = "echo hi |& cat"
    expected = [
        PipeNode(
            is_background=False,
            items=[
                CommandNode(
                    1,
                    [],
                    [argchars("echo"), argchars("hi")],
                    [DupRedirNode("ToFD", ("fixed", 2), ("fixed", 1), move=False)],
                ),
                CommandNode(1, [], [argchars("cat")], []),
            ],
        )
    ]

    actual = shfmt_to_shasta_nodes(script)

    assert_shasta_equal(actual, expected)


def test_shfmt_script_background() -> None:
    script = "echo hi &"
    expected = [
        BackgroundNode(
            line_number=None,
            node=CommandNode(1, [], [argchars("echo"), argchars("hi")], []),
            redir_list=[],
            no_braces=True,
        )
    ]

    actual = shfmt_to_shasta_nodes(script)

    assert_shasta_equal(actual, expected)


def test_shfmt_script_background_pipe() -> None:
    script = "echo hi | cat &"
    expected = [
        BackgroundNode(
            line_number=None,
            node=PipeNode(
                is_background=False,
                items=[
                    CommandNode(1, [], [argchars("echo"), argchars("hi")], []),
                    CommandNode(1, [], [argchars("cat")], []),
                ],
            ),
            redir_list=[],
            no_braces=True,
        )
    ]

    actual = shfmt_to_shasta_nodes(script)

    assert_shasta_equal(actual, expected)


def test_shfmt_script_negation() -> None:
    script = "! echo hi"
    expected = [
        NotNode(
            CommandNode(1, [], [argchars("echo"), argchars("hi")], []), no_braces=True
        )
    ]

    actual = shfmt_to_shasta_nodes(script)

    assert_shasta_equal(actual, expected)


def test_shfmt_script_time_clause() -> None:
    script = "time echo hi"
    expected = [
        TimeNode(
            time_posix=False,
            command=CommandNode(1, [], [argchars("echo"), argchars("hi")], []),
        )
    ]

    actual = shfmt_to_shasta_nodes(script)

    assert_shasta_equal(actual, expected)


def test_shfmt_script_time_clause_posix() -> None:
    script = "time -p echo hi"
    expected = [
        TimeNode(
            time_posix=True,
            command=CommandNode(1, [], [argchars("echo"), argchars("hi")], []),
        )
    ]

    actual = shfmt_to_shasta_nodes(script)

    assert_shasta_equal(actual, expected)


def test_shfmt_script_function_decl() -> None:
    script = "foo() { echo hi; }"
    expected = [
        DefunNode(
            line_number=1,
            name=argchars("foo"),
            body=CommandNode(1, [], [argchars("echo"), argchars("hi")], []),
            bash_mode=False,
        )
    ]

    actual = shfmt_to_shasta_nodes(script)

    assert_shasta_equal(actual, expected)


def test_shfmt_script_coproc() -> None:
    script = "coproc echo hi"
    expected = [
        CoprocNode(
            name=[],
            body=CommandNode(1, [], [argchars("echo"), argchars("hi")], []),
        )
    ]

    actual = shfmt_to_shasta_nodes(script)

    assert_shasta_equal(actual, expected)


def test_shfmt_script_subshell() -> None:
    script = "(echo hi)"
    expected = [
        SubshellNode(
            line_number=1,
            body=CommandNode(1, [], [argchars("echo"), argchars("hi")], []),
            redir_list=[],
        )
    ]

    actual = shfmt_to_shasta_nodes(script)

    assert_shasta_equal(actual, expected)


def test_shfmt_script_group() -> None:
    script = "{ echo hi; }"
    expected = [GroupNode(CommandNode(1, [], [argchars("echo"), argchars("hi")], []))]

    actual = shfmt_to_shasta_nodes(script)

    assert_shasta_equal(actual, expected)


def test_shfmt_script_group_redir() -> None:
    script = "{ echo hi; } > out"
    expected = [
        RedirNode(
            line_number=None,
            node=GroupNode(CommandNode(1, [], [argchars("echo"), argchars("hi")], [])),
            redir_list=[FileRedirNode("To", ("fixed", 1), argchars("out"))],
        )
    ]

    actual = shfmt_to_shasta_nodes(script)

    assert_shasta_equal(actual, expected)


def test_shfmt_script_complex_one() -> None:
    script = (
        "echo hi\n"
        "if true; then echo ok; fi\n"
        "{ echo grp; } > out\n"
        "(echo sub)\n"
        "foo() { echo fn; }\n"
        "coproc echo co\n"
        "time -p echo tm\n"
        "echo a | cat &\n"
        "[[ -n x ]]\n"
        "((i+=1))\n"
    )
    expected = [
        CommandNode(1, [], [argchars("echo"), argchars("hi")], []),
        IfNode(
            cond=CommandNode(2, [], [argchars("true")], []),
            then_b=CommandNode(2, [], [argchars("echo"), argchars("ok")], []),
            else_b=None,
        ),
        RedirNode(
            line_number=None,
            node=GroupNode(CommandNode(3, [], [argchars("echo"), argchars("grp")], [])),
            redir_list=[FileRedirNode("To", ("fixed", 1), argchars("out"))],
        ),
        SubshellNode(
            line_number=4,
            body=CommandNode(4, [], [argchars("echo"), argchars("sub")], []),
            redir_list=[],
        ),
        DefunNode(
            line_number=5,
            name=argchars("foo"),
            body=CommandNode(5, [], [argchars("echo"), argchars("fn")], []),
            bash_mode=False,
        ),
        CoprocNode(
            name=[],
            body=CommandNode(6, [], [argchars("echo"), argchars("co")], []),
        ),
        TimeNode(
            time_posix=True,
            command=CommandNode(7, [], [argchars("echo"), argchars("tm")], []),
        ),
        BackgroundNode(
            line_number=None,
            node=PipeNode(
                is_background=False,
                items=[
                    CommandNode(8, [], [argchars("echo"), argchars("a")], []),
                    CommandNode(8, [], [argchars("cat")], []),
                ],
            ),
            redir_list=[],
            no_braces=True,
        ),
        cond_unary("-n", cond_term("x", line=9), line=9),
        ArithNode(line_number=10, body=[argchars("i += 1")]),
    ]

    actual = shfmt_to_shasta_nodes(script)

    assert_shasta_equal(actual, expected)


def test_shfmt_script_complex_two() -> None:
    script = (
        "for i in a b; do echo hi; done\n"
        "while false; do echo no; done\n"
        "case x in a) echo one ;; esac\n"
        "echo ${a:-b} ${#a}\n"
        "echo <(echo hi) >(cat)\n"
        "echo @(a) ?(b) *(c) +(d) !(e)\n"
        "cat <<EOF\n"
        "body\n"
        "EOF\n"
    )
    expected = [
        ForNode(
            line_number=1,
            argument=[argchars("a"), argchars("b")],
            body=CommandNode(1, [], [argchars("echo"), argchars("hi")], []),
            variable=argchars("i"),
        ),
        WhileNode(
            test=CommandNode(2, [], [argchars("false")], []),
            body=CommandNode(2, [], [argchars("echo"), argchars("no")], []),
        ),
        CaseNode(
            line_number=3,
            argument=argchars("x"),
            cases=[
                {
                    "cpattern": [argchars("a")],
                    "cbody": CommandNode(
                        3, [], [argchars("echo"), argchars("one")], []
                    ),
                    "fallthrough": False,
                }
            ],
        ),
        CommandNode(
            4,
            [],
            [
                argchars("echo"),
                [VArgChar("Minus", True, "a", argchars("b"))],
                [VArgChar("Length", False, "a", [])],
            ],
            [],
        ),
        CommandNode(
            5,
            [],
            [
                argchars("echo"),
                [
                    PArgChar(
                        "<(", CommandNode(5, [], [argchars("echo"), argchars("hi")], [])
                    )
                ],
                [PArgChar(">(", CommandNode(5, [], [argchars("cat")], []))],
            ],
            [],
        ),
        CommandNode(
            6,
            [],
            [
                argchars("echo"),
                argchars("@(a)"),
                argchars("?(b)"),
                argchars("*(c)"),
                argchars("+(d)"),
                argchars("!(e)"),
            ],
            [],
        ),
        CommandNode(
            7,
            [],
            [argchars("cat")],
            [HeredocRedirNode("XHere", ("fixed", 0), argchars("body\n"), False, "EOF")],
        ),
    ]

    actual = shfmt_to_shasta_nodes(script)

    assert_shasta_equal(actual, expected)


def test_shfmt_script_if_clause() -> None:
    script = "if true; then echo hi; fi"
    expected = [
        IfNode(
            cond=CommandNode(1, [], [argchars("true")], []),
            then_b=CommandNode(1, [], [argchars("echo"), argchars("hi")], []),
            else_b=None,
        )
    ]

    actual = shfmt_to_shasta_nodes(script)

    assert_shasta_equal(actual, expected)


def test_shfmt_script_test_clause() -> None:
    script = "[[ -n x ]]"
    expected = [cond_unary("-n", cond_term("x", line=1), line=1)]

    actual = shfmt_to_shasta_nodes(script)

    assert_shasta_equal(actual, expected)


def test_shfmt_script_test_clause_flags() -> None:
    flags = [
        "-e",
        "-f",
        "-d",
        "-c",
        "-b",
        "-p",
        "-S",
        "-L",
        "-k",
        "-g",
        "-u",
        "-G",
        "-O",
        "-N",
        "-r",
        "-w",
        "-x",
        "-s",
        "-t",
        "-z",
        "-n",
        "-o",
        "-v",
        "-R",
    ]
    for flag in flags:
        script = f"[[ {flag} x ]]"
        expected = [cond_unary(flag, cond_term("x", line=1), line=1)]

        actual = shfmt_to_shasta_nodes(script)

        assert_shasta_equal(actual, expected)


def test_shfmt_script_test_clause_binary_ops() -> None:
    cases = [
        ("[[ a -eq b ]]", ["[[", "a", "-eq", "b", "]]"]),
        ("[[ a -ne b ]]", ["[[", "a", "-ne", "b", "]]"]),
        ("[[ a -lt b ]]", ["[[", "a", "-lt", "b", "]]"]),
        ("[[ a -gt b ]]", ["[[", "a", "-gt", "b", "]]"]),
        ("[[ a -le b ]]", ["[[", "a", "-le", "b", "]]"]),
        ("[[ a -ge b ]]", ["[[", "a", "-ge", "b", "]]"]),
        ("[[ a -nt b ]]", ["[[", "a", "-nt", "b", "]]"]),
        ("[[ a -ot b ]]", ["[[", "a", "-ot", "b", "]]"]),
        ("[[ a -ef b ]]", ["[[", "a", "-ef", "b", "]]"]),
        ("[[ a = b ]]", ["[[", "a", "=", "b", "]]"]),
        ("[[ a == b ]]", ["[[", "a", "==", "b", "]]"]),
        ("[[ a != b ]]", ["[[", "a", "!=", "b", "]]"]),
        ("[[ a < b ]]", ["[[", "a", "<", "b", "]]"]),
        ("[[ a > b ]]", ["[[", "a", ">", "b", "]]"]),
        ("[[ a =~ b ]]", ["[[", "a", "=~", "b", "]]"]),
        ("[[ a && b ]]", ["[[", "a", "&&", "b", "]]"]),
        ("[[ a || b ]]", ["[[", "a", "||", "b", "]]"]),
    ]
    for script, tokens in cases:
        left = cond_term(tokens[1], line=1)
        right = cond_term(tokens[3], line=1)
        if tokens[2] == "&&":
            expected = [cond_and(left, right, line=1)]
        elif tokens[2] == "||":
            expected = [cond_or(left, right, line=1)]
        else:
            expected = [cond_binary(tokens[2], left, right, line=1)]

        actual = shfmt_to_shasta_nodes(script)

        assert_shasta_equal(actual, expected)


def test_shfmt_script_binary_cmd_ops() -> None:
    cases = [
        (
            "true && false",
            AndNode(
                left_operand=CommandNode(1, [], [argchars("true")], []),
                right_operand=CommandNode(1, [], [argchars("false")], []),
                no_braces=True,
            ),
        ),
        (
            "true || false",
            OrNode(
                left_operand=CommandNode(1, [], [argchars("true")], []),
                right_operand=CommandNode(1, [], [argchars("false")], []),
                no_braces=True,
            ),
        ),
        (
            "echo hi | cat",
            PipeNode(
                is_background=False,
                items=[
                    CommandNode(1, [], [argchars("echo"), argchars("hi")], []),
                    CommandNode(1, [], [argchars("cat")], []),
                ],
            ),
        ),
    ]
    for script, expected_node in cases:
        actual = shfmt_to_shasta_nodes(script)

        assert_shasta_equal(actual, [expected_node])


def test_shfmt_script_redir_all() -> None:
    script = "echo hi &> out"
    expected = [
        CommandNode(
            1,
            [],
            [argchars("echo"), argchars("hi")],
            [SingleArgRedirNode("ErrAndOut", ("var", argchars("out")))],
        )
    ]

    actual = shfmt_to_shasta_nodes(script)

    assert_shasta_equal(actual, expected)


def test_shfmt_script_redir_ops() -> None:
    cases = [
        (
            "echo hi > out",
            [argchars("echo"), argchars("hi")],
            [FileRedirNode("To", ("fixed", 1), argchars("out"))],
        ),
        (
            "echo hi >> out",
            [argchars("echo"), argchars("hi")],
            [FileRedirNode("Append", ("fixed", 1), argchars("out"))],
        ),
        (
            "echo hi >| out",
            [argchars("echo"), argchars("hi")],
            [FileRedirNode("Clobber", ("fixed", 1), argchars("out"))],
        ),
        (
            "cat < in",
            [argchars("cat")],
            [FileRedirNode("From", ("fixed", 0), argchars("in"))],
        ),
        (
            "cat <> inout",
            [argchars("cat")],
            [FileRedirNode("FromTo", ("fixed", 0), argchars("inout"))],
        ),
        (
            "cat <<EOF\nbody\nEOF",
            [argchars("cat")],
            [HeredocRedirNode("XHere", ("fixed", 0), argchars("body\n"), False, "EOF")],
        ),
        (
            "cat <<-EOF\nbody\nEOF",
            [argchars("cat")],
            [HeredocRedirNode("XHere", ("fixed", 0), argchars("body\n"), True, "EOF")],
        ),
        (
            "cat <<< data",
            [argchars("cat")],
            [FileRedirNode("ReadingString", ("fixed", 0), argchars("data"))],
        ),
        (
            "echo hi >&2",
            [argchars("echo"), argchars("hi")],
            [DupRedirNode("ToFD", ("fixed", 1), ("fixed", 2), move=False)],
        ),
        (
            "cat <&0",
            [argchars("cat")],
            [DupRedirNode("FromFD", ("fixed", 0), ("fixed", 0), move=False)],
        ),
        (
            "echo hi &>> out",
            [argchars("echo"), argchars("hi")],
            [SingleArgRedirNode("AppendErrAndOut", ("var", argchars("out")))],
        ),
    ]
    for script, args, redirs in cases:
        expected = [CommandNode(1, [], args, redirs)]

        actual = shfmt_to_shasta_nodes(script)

        assert_shasta_equal(actual, expected)


def test_shfmt_script_param_exp_ops() -> None:
    script = (
        "echo ${a-b} ${a:-b} ${a+b} ${a:+b} ${a?b} ${a:?b} ${a=b} ${a:=b} "
        "${a%p} ${a%%p} ${a#p} ${a##p} ${#a}"
    )
    expected = [
        CommandNode(
            1,
            [],
            [
                argchars("echo"),
                [VArgChar("Minus", False, "a", argchars("b"))],
                [VArgChar("Minus", True, "a", argchars("b"))],
                [VArgChar("Plus", False, "a", argchars("b"))],
                [VArgChar("Plus", True, "a", argchars("b"))],
                [VArgChar("Question", False, "a", argchars("b"))],
                [VArgChar("Question", True, "a", argchars("b"))],
                [VArgChar("Assign", False, "a", argchars("b"))],
                [VArgChar("Assign", True, "a", argchars("b"))],
                [VArgChar("TrimR", False, "a", argchars("p"))],
                [VArgChar("TrimRMax", False, "a", argchars("p"))],
                [VArgChar("TrimL", False, "a", argchars("p"))],
                [VArgChar("TrimLMax", False, "a", argchars("p"))],
                [VArgChar("Length", False, "a", [])],
            ],
            [],
        )
    ]

    actual = shfmt_to_shasta_nodes(script)

    assert_shasta_equal(actual, expected)


def test_shfmt_script_param_exp_names() -> None:
    script = "echo ${!arr*} ${!arr@}"
    expected = [
        CommandNode(
            1,
            [],
            [argchars("echo"), argchars("${!arr*}"), argchars("${!arr@}")],
            [],
        )
    ]

    actual = shfmt_to_shasta_nodes(script)

    assert_shasta_equal(actual, expected)


def test_shfmt_script_proc_subst_ops() -> None:
    script = "echo <(echo hi) >(cat)"
    expected = [
        CommandNode(
            1,
            [],
            [
                argchars("echo"),
                [
                    PArgChar(
                        "<(", CommandNode(1, [], [argchars("echo"), argchars("hi")], [])
                    )
                ],
                [PArgChar(">(", CommandNode(1, [], [argchars("cat")], []))],
            ],
            [],
        )
    ]

    actual = shfmt_to_shasta_nodes(script)

    assert_shasta_equal(actual, expected)


def test_shfmt_script_extglob_ops() -> None:
    script = "echo @(a) ?(b) *(c) +(d) !(e)"
    expected = [
        CommandNode(
            1,
            [],
            [
                argchars("echo"),
                argchars("@(a)"),
                argchars("?(b)"),
                argchars("*(c)"),
                argchars("+(d)"),
                argchars("!(e)"),
            ],
            [],
        )
    ]

    actual = shfmt_to_shasta_nodes(script)

    assert_shasta_equal(actual, expected)


def test_shfmt_script_case_ops() -> None:
    script = "case x in a) echo hi ;& b) echo bye ;; esac"
    expected = [
        CaseNode(
            line_number=1,
            argument=argchars("x"),
            cases=[
                {
                    "cpattern": [argchars("a")],
                    "cbody": CommandNode(1, [], [argchars("echo"), argchars("hi")], []),
                    "fallthrough": True,
                },
                {
                    "cpattern": [argchars("b")],
                    "cbody": CommandNode(
                        1, [], [argchars("echo"), argchars("bye")], []
                    ),
                    "fallthrough": False,
                },
            ],
        )
    ]

    actual = shfmt_to_shasta_nodes(script)

    assert_shasta_equal(actual, expected)


def test_shfmt_script_arithm_ops() -> None:
    cases = [
        ("((1+2))", "1 + 2"),
        ("((1-2))", "1 - 2"),
        ("((1*2))", "1 * 2"),
        ("((1/2))", "1 / 2"),
        ("((1%2))", "1 % 2"),
        ("((1**2))", "1 ** 2"),
        ("((1==2))", "1 == 2"),
        ("((1!=2))", "1 != 2"),
        ("((1>2))", "1 > 2"),
        ("((1<2))", "1 < 2"),
        ("((1>=2))", "1 >= 2"),
        ("((1<=2))", "1 <= 2"),
        ("((1<<2))", "1 << 2"),
        ("((1>>2))", "1 >> 2"),
        ("((1&2))", "1 & 2"),
        ("((1|2))", "1 | 2"),
        ("((1^2))", "1 ^ 2"),
        ("((1&&2))", "1 && 2"),
        ("((1||2))", "1 || 2"),
        ("((1,2))", "1 , 2"),
        ("((1?2:3))", "1 ? 2 : 3"),
        ("((i=1))", "i = 1"),
        ("((i+=1))", "i += 1"),
        ("((i-=1))", "i -= 1"),
        ("((i*=1))", "i *= 1"),
        ("((i/=1))", "i /= 1"),
        ("((i%=1))", "i %= 1"),
        ("((i&=1))", "i &= 1"),
        ("((i|=1))", "i |= 1"),
        ("((i^=1))", "i ^= 1"),
        ("((i<<=1))", "i <<= 1"),
        ("((i>>=1))", "i >>= 1"),
        ("((!i))", "!i"),
        ("((~i))", "~i"),
        ("((++i))", "++i"),
        ("((--i))", "--i"),
        ("((i++))", "i++"),
        ("((i--))", "i--"),
    ]
    for script, expr in cases:
        expected = [ArithNode(line_number=1, body=[argchars(expr)])]

        actual = shfmt_to_shasta_nodes(script)

        assert_shasta_equal(actual, expected)


def test_shfmt_script_case_clause() -> None:
    script = "case x in a) echo hi ;; esac"
    expected = [
        CaseNode(
            line_number=1,
            argument=argchars("x"),
            cases=[
                {
                    "cpattern": [argchars("a")],
                    "cbody": CommandNode(1, [], [argchars("echo"), argchars("hi")], []),
                    "fallthrough": False,
                }
            ],
        )
    ]

    actual = shfmt_to_shasta_nodes(script)

    assert_shasta_equal(actual, expected)


def run_tests() -> int:
    tests = [
        test_call_expr_with_assign,
        test_binary_cmd_ops,
        test_pipe_all_injects_dup,
        test_if_and_while_until,
        test_for_clause_variants,
        test_case_clause_fallthrough,
        test_redirection_variants,
        test_word_parts_and_param_exp,
        test_param_exp_names_fallback,
        test_test_clause_binary,
        test_file_to_nodes,
        test_shfmt_script_simple_call,
        test_shfmt_script_escape_param,
        test_shfmt_script_escape_glob_literal,
        test_shfmt_script_pipe_all,
        test_shfmt_script_background,
        test_shfmt_script_background_pipe,
        test_shfmt_script_negation,
        test_shfmt_script_time_clause,
        test_shfmt_script_time_clause_posix,
        test_shfmt_script_function_decl,
        test_shfmt_script_coproc,
        test_shfmt_script_subshell,
        test_shfmt_script_group,
        test_shfmt_script_group_redir,
        test_shfmt_script_complex_one,
        test_shfmt_script_complex_two,
        test_shfmt_script_if_clause,
        test_shfmt_script_test_clause,
        test_shfmt_script_test_clause_flags,
        test_shfmt_script_test_clause_binary_ops,
        test_shfmt_script_binary_cmd_ops,
        test_shfmt_script_redir_all,
        test_shfmt_script_redir_ops,
        test_shfmt_script_param_exp_ops,
        test_shfmt_script_param_exp_names,
        test_shfmt_script_proc_subst_ops,
        test_shfmt_script_extglob_ops,
        test_shfmt_script_case_ops,
        test_shfmt_script_arithm_ops,
        test_shfmt_script_case_clause,
    ]
    failures = 0
    for test in tests:
        try:
            test()
            print(f"{test.__name__}: OK")
        except AssertionError as exc:
            failures += 1
            print(f"{test.__name__}: FAIL")
            print(exc)
    return failures


if __name__ == "__main__":
    raise SystemExit(run_tests())
