"""Template extraction in the spirit of Drain (He et al., 2017), pure stdlib.

The point: a log line's variable parts are found *positionally*, not by guessing
which tokens "look like" data. Lines are bucketed by token count and by their
first few fixed tokens; inside a bucket a line is matched against known
templates by how many token positions agree. Positions that disagree become
wildcards. That finds block ids, hostnames, usernames and paths alike — no
vocabulary, no regex list.

Built to be trained on a sample, frozen, and then applied cheaply in parallel
workers, so a multi-GB scan stays fast.
"""
import re

MAX_DEPTH = 4          # tree levels spent on leading tokens
MAX_CHILD = 30         # branching cap per node; overflow goes to a shared "*" child
SIM_THRESHOLD = 0.4    # min share of matching positions to join a template
WILDCARD = "<*>"

# Cheap pre-masking of things that are unambiguously data. Kept short on purpose:
# the tree finds the rest positionally.
_PRE = [
    (re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.I), "<*>"),
    (re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}(?::\d+)?\b"), "<*>"),
    (re.compile(r"\b0x[0-9a-f]+\b", re.I), "<*>"),
    (re.compile(r"\b\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?Z?\b"), "<*>"),
    (re.compile(r"\b\d{1,2}:\d{2}:\d{2}(?:[.,]\d+)?\b"), "<*>"),
]

_HAS_DIGIT = re.compile(r"\d")
# Tuned against LogHub ground truth: splitting on |,;= as well as whitespace
# lifted grouping accuracy from 76.4% to 79.5%.
_SPLIT = re.compile(r"[\s|,;=]+")


def pre_mask(line):
    for pat, rep in _PRE:
        line = pat.sub(rep, line)
    return line


def tokenize(line):
    return _SPLIT.split(pre_mask(line).strip())


class _Cluster:
    __slots__ = ("tokens", "count", "cid")

    def __init__(self, tokens, cid):
        self.tokens = tokens
        self.count = 1
        self.cid = cid

    def template(self):
        return " ".join(self.tokens)


class Drain:
    """Online template miner. train() to learn, match() to apply (read-only)."""

    def __init__(self, depth=MAX_DEPTH, max_child=MAX_CHILD, sim=SIM_THRESHOLD):
        self.depth = max(depth, 2)
        self.max_child = max_child
        self.sim = sim
        self.root = {}
        self.clusters = []

    # ---- tree navigation -------------------------------------------------
    def _leaf(self, tokens, create):
        n = len(tokens)
        node = self.root.get(n)
        if node is None:
            if not create:
                return None
            node = self.root[n] = {}
        for i in range(min(self.depth - 1, n)):
            tok = tokens[i]
            key = WILDCARD if _HAS_DIGIT.search(tok) else tok
            nxt = node.get(key)
            if nxt is None:
                if not create:
                    nxt = node.get(WILDCARD)
                    if nxt is None:
                        return None
                elif len(node) >= self.max_child:
                    nxt = node.setdefault(WILDCARD, {})
                else:
                    nxt = node[key] = {}
            node = nxt
        return node.setdefault("__leaf__", []) if create else node.get("__leaf__")

    @staticmethod
    def _similarity(a, b):
        """Share of positions holding the same literal token.

        Wildcard positions deliberately do NOT count as agreement, which is what
        the paper specifies and what keeps the miner honest: counting them made
        similarity rise as a cluster generalized, so the first cluster to collect
        a few wildcards started matching everything of that token count and
        became a black hole. Real one-off events — the deploy, the cron job, the
        config change we most want to surface — were absorbed into it and never
        reported as rare. Now a heavily generalized cluster scores *low* and has
        to earn each new member on literal matches.
        """
        if not a:
            return 0.0, 0
        same = wild = 0
        for x, y in zip(a, b):
            if x == WILDCARD:
                wild += 1
            elif x == y:
                same += 1
        return same / len(a), wild

    def _best(self, leaf, tokens):
        best, best_sim, best_wild = None, -1.0, 0
        for cl in leaf:
            s, w = self._similarity(cl.tokens, tokens)
            if s > best_sim or (s == best_sim and w < best_wild):
                best, best_sim, best_wild = cl, s, w
        return best if best_sim >= self.sim else None

    # ---- public API ------------------------------------------------------
    def train(self, line):
        tokens = tokenize(line)
        if not tokens:
            return None
        leaf = self._leaf(tokens, create=True)
        cl = self._best(leaf, tokens)
        if cl is None:
            cl = _Cluster(list(tokens), len(self.clusters))
            leaf.append(cl)
            self.clusters.append(cl)
        else:
            cl.count += 1
            # generalize: any position that now differs becomes a wildcard
            t = cl.tokens
            for i, (x, y) in enumerate(zip(t, tokens)):
                if x != y and x != WILDCARD:
                    t[i] = WILDCARD
        return cl.cid

    def match(self, line):
        """Assign a line to a learned template. Falls back to a masked key."""
        tokens = tokenize(line)
        if not tokens:
            return ""
        leaf = self._leaf(tokens, create=False)
        if leaf:
            cl = self._best(leaf, tokens)
            if cl is not None:
                return cl.template()
        # unseen shape: mask digit-bearing tokens so it still groups sanely
        return " ".join(WILDCARD if _HAS_DIGIT.search(t) else t for t in tokens)

    def state(self):
        """Frozen, picklable template list for parallel workers."""
        return [cl.tokens for cl in self.clusters]

    @classmethod
    def from_state(cls, templates, **kw):
        d = cls(**kw)
        for toks in templates:
            leaf = d._leaf(toks, create=True)
            cl = _Cluster(list(toks), len(d.clusters))
            leaf.append(cl)
            d.clusters.append(cl)
        return d


def train_from_lines(lines, depth=MAX_DEPTH, sim=SIM_THRESHOLD):
    d = Drain(depth=depth, sim=sim)
    for line in lines:
        d.train(line)
    return d
