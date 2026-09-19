# Hidden test suites. Each task: prompt spec + tests(mod) -> (passed, total)

TASKS = {}

def task(name, fn, prompt, tests):
    TASKS[name] = {"fn": fn, "prompt": prompt, "tests": tests}

# ---------- 1. longest valid parentheses ----------
task("lvp", "longest_valid_parentheses",
"""Write a Python function:

    def longest_valid_parentheses(s: str) -> int

Given a string containing only '(' and ')', return the length of the longest
contiguous substring that is a well-formed (balanced) parentheses string.

Examples: "(()" -> 2 ; ")()())" -> 4 ; "" -> 0 ; "()(()" -> 2
""",
[
    ("(()", 2), (")()())", 4), ("", 0), ("()(()", 2), ("()", 2),
    ("(((((", 0), (")))))", 0), ("()(())", 6), ("(()())", 6),
    ("()()", 4), (")()()(", 4), ("(()))())(", 4), ("((()))", 6),
    ("()(()))))", 6), ("(" * 500 + ")" * 500, 1000),
])

# ---------- 2. minimum window substring ----------
task("minwin", "min_window",
"""Write a Python function:

    def min_window(s: str, t: str) -> str

Return the shortest contiguous substring of s that contains every character of t
including duplicates (multiset containment). If no such window exists, return "".
If several windows tie for shortest, return the leftmost one.

Examples: min_window("ADOBECODEBANC","ABC") -> "BANC" ; min_window("a","aa") -> ""
""",
[
    (("ADOBECODEBANC", "ABC"), "BANC"), (("a", "a"), "a"), (("a", "aa"), ""),
    (("", "a"), ""), (("a", ""), ""), (("aa", "aa"), "aa"),
    (("bba", "ab"), "ba"), (("abc", "cba"), "abc"),
    (("cabwefgewcwaefgcf", "cae"), "cwae"),
    (("aaaaaaaaaaaabbbbbcdd", "abcdd"), "abbbbbcdd"),
    (("ab", "b"), "b"), (("abcabdec", "abc"), "abc"),
])

# ---------- 3. expression calculator ----------
task("calc", "calculate",
"""Write a Python function:

    def calculate(expr: str) -> int

Evaluate an integer arithmetic expression string supporting + - * / and
parentheses, with standard precedence. Unary minus is allowed (e.g. "-3", "-(2+1)",
"3*-2"). Whitespace may appear anywhere and must be ignored.
Division is INTEGER division that TRUNCATES TOWARD ZERO (so -7/2 == -3, not -4).
Input is always a valid expression. Do not use eval().

Examples: "1+1" -> 2 ; " 6-4/2 " -> 4 ; "2*(5+5*2)/3+(6/2+8)" -> 21
""",
[
    ("1+1", 2), (" 6-4/2 ", 4), ("2*(5+5*2)/3+(6/2+8)", 21),
    ("-3", -3), ("-(2+1)", -3), ("3*-2", -6), ("-7/2", -3), ("7/-2", -3),
    ("0-2147483647", -2147483647), ("(1+(4+5+2)-3)+(6+8)", 23),
    ("2-(5-6)", 3), ("1-(-2)", 3), ("- (3 + (4 + 5))", -12),
    ("100/3", 33), ("-100/3", -33), ("((((1))))", 1),
    ("2*3*4/5", 4), ("1+2*3-4/2", 5), ("10-3*2+(8/4)", 6),
])

# ---------- 4. word break all sentences ----------
task("wordbreak", "word_break_all",
"""Write a Python function:

    def word_break_all(s: str, words: list) -> list

Return ALL possible sentences formed by splitting s into a sequence of words from
the list `words` (each word reusable any number of times), joined by single spaces.
Return the results sorted in ascending lexicographic order. If none, return [].

Example: word_break_all("catsanddog", ["cat","cats","and","sand","dog"])
  -> ["cat sand dog", "cats and dog"]
""",
[
    (("catsanddog", ["cat","cats","and","sand","dog"]), ["cat sand dog","cats and dog"]),
    (("pineapplepenapple", ["apple","pen","applepen","pine","pineapple"]),
     ["pine apple pen apple","pine applepen apple","pineapple pen apple"]),
    (("catsandog", ["cats","dog","sand","and","cat"]), []),
    (("", ["a"]), []),
    (("a", ["a"]), ["a"]),
    (("aaa", ["a","aa"]), ["a a a","a aa","aa a"]),
    (("ab", ["a","b","ab"]), ["a b","ab"]),
    (("abcd", ["x"]), []),
])

# ---------- 5. lexicographically smallest topological order ----------
task("topo", "topo_order",
"""Write a Python function:

    def topo_order(n: int, edges: list) -> list

Nodes are 0..n-1. `edges` is a list of (u, v) pairs meaning u must come before v.
Return the lexicographically SMALLEST topological ordering as a list of ints.
If the graph has a cycle, return None. Duplicate edges may appear.

Example: topo_order(4, [(0,1),(2,3)]) -> [0,1,2,3]
""",
[
    ((4, [(0,1),(2,3)]), [0,1,2,3]),
    ((3, [(1,0),(2,0)]), [1,2,0]),
    ((2, [(0,1),(1,0)]), None),
    ((1, []), [0]),
    ((0, []), []),
    ((5, []), [0,1,2,3,4]),
    ((4, [(3,0),(3,1),(0,2)]), [3,0,1,2]),
    ((3, [(0,1),(0,1),(1,2)]), [0,1,2]),
    ((3, [(2,0),(0,1),(1,2)]), None),
    ((6, [(5,0),(5,2),(4,0),(4,1),(2,3),(3,1)]), [4,5,0,2,3,1]),
])

# ---------- 6. query string parser ----------
task("qs", "parse_qs",
"""Write a Python function:

    def parse_qs(query: str) -> dict

Parse a URL query string into a dict mapping each key to the LIST of its values,
in order of appearance. Rules:
  - Pairs are separated by '&'. Empty segments are skipped.
  - A segment with no '=' is a bare key whose value is the empty string.
  - Only the FIRST '=' splits key from value ("a=b=c" -> key "a", value "b=c").
  - '+' in either key or value decodes to a space.
  - Percent-escapes (%XX, case-insensitive hex) decode to bytes, then UTF-8 decode.
  - Segments whose key is empty after decoding are skipped entirely.
Do not use urllib or any stdlib query-parsing helper; implement the decoding.

Example: parse_qs("a=1&b=2&a=3") -> {"a": ["1","3"], "b": ["2"]}
""",
[
    ("a=1&b=2&a=3", {"a":["1","3"],"b":["2"]}),
    ("", {}),
    ("a", {"a":[""]}),
    ("a=", {"a":[""]}),
    ("=v", {}),
    ("a=b=c", {"a":["b=c"]}),
    ("a+b=c+d", {"a b":["c d"]}),
    ("a%20b=c%20d", {"a b":["c d"]}),
    ("a=%E2%9C%93", {"a":["✓"]}),
    ("a=%e2%9c%93", {"a":["✓"]}),
    ("&&a=1&&", {"a":["1"]}),
    ("x=1&x=2&x=3", {"x":["1","2","3"]}),
    ("k%3D=v%26", {"k=":["v&"]}),
    ("a=1&&=2&b", {"a":["1"],"b":[""]}),
])
