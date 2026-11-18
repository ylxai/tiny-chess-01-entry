import json
import os
import sys
import urllib.error
import urllib.request

ENV_URL = os.environ.get("MAKEFUN_ENV_URL") or sys.exit("MAKEFUN_ENV_URL is not set")

FILES = "abcdefgh"


def sq_name(s):
    return FILES[s % 8] + str(s // 8 + 1)


def name_sq(name):
    return (int(name[1]) - 1) * 8 + FILES.index(name[0])


def parse_fen(fen):
    parts = fen.split()
    board = ["."] * 64
    rank = 7
    file_ = 0
    for c in parts[0]:
        if c == "/":
            rank -= 1
            file_ = 0
        elif c.isdigit():
            file_ += int(c)
        else:
            board[rank * 8 + file_] = c
            file_ += 1
    turn = parts[1]
    castle = parts[2] if len(parts) > 2 else "-"
    ep = parts[3] if len(parts) > 3 else "-"
    ep_sq = None if ep == "-" else name_sq(ep)
    return board, turn, castle, ep_sq


ORTH_D = ((1, 0), (-1, 0), (0, 1), (0, -1))
DIAG_D = ((1, 1), (1, -1), (-1, 1), (-1, -1))
ALL_D = ORTH_D + DIAG_D
KNIGHT_D = ((1, 2), (2, 1), (-1, 2), (-2, 1), (1, -2), (2, -1), (-1, -2), (-2, -1))

KNIGHT_MOVES = [[] for _ in range(64)]
KING_MOVES = [[] for _ in range(64)]
PAWN_CAPS = {"w": [[] for _ in range(64)], "b": [[] for _ in range(64)]}
RAYS = {d: [[] for _ in range(64)] for d in ALL_D}

for _s in range(64):
    _f, _r = _s % 8, _s // 8
    for _df, _dr in KNIGHT_D:
        _nf, _nr = _f + _df, _r + _dr
        if 0 <= _nf < 8 and 0 <= _nr < 8:
            KNIGHT_MOVES[_s].append(_nr * 8 + _nf)
    for _df, _dr in ALL_D:
        _nf, _nr = _f + _df, _r + _dr
        if 0 <= _nf < 8 and 0 <= _nr < 8:
            KING_MOVES[_s].append(_nr * 8 + _nf)
    for _df in (-1, 1):
        _nf, _nr = _f + _df, _r + 1
        if 0 <= _nf < 8 and 0 <= _nr < 8:
            PAWN_CAPS["w"][_s].append(_nr * 8 + _nf)
        _nf, _nr = _f + _df, _r - 1
        if 0 <= _nf < 8 and 0 <= _nr < 8:
            PAWN_CAPS["b"][_s].append(_nr * 8 + _nf)
    for _d in ALL_D:
        _df, _dr = _d
        _nf, _nr = _f + _df, _r + _dr
        _ray = []
        while 0 <= _nf < 8 and 0 <= _nr < 8:
            _ray.append(_nr * 8 + _nf)
            _nf += _df
            _nr += _dr
        RAYS[_d][_s] = _ray

BISHOP_D = DIAG_D
ROOK_D = ORTH_D
QUEEN_D = ALL_D


def is_white(p):
    return p.isupper()


def color_of(p):
    return "w" if p.isupper() else "b"


def slide_targets(board, s, dirs):
    out = []
    for d in dirs:
        for t in RAYS[d][s]:
            out.append(t)
            if board[t] != ".":
                break
    return out


def attacked_by(board, target, color):
    for s in range(64):
        p = board[s]
        if p == "." or color_of(p) != color:
            continue
        low = p.lower()
        if low == "p":
            if target in PAWN_CAPS[color][s]:
                return True
        elif low == "n":
            if target in KNIGHT_MOVES[s]:
                return True
        elif low == "k":
            if target in KING_MOVES[s]:
                return True
        elif low == "b":
            if target in slide_targets(board, s, BISHOP_D):
                return True
        elif low == "r":
            if target in slide_targets(board, s, ROOK_D):
                return True
        else:
            if target in slide_targets(board, s, QUEEN_D):
                return True
    return False


class State:
    __slots__ = ("board", "turn", "castle", "ep")

    def __init__(self, board, turn, castle, ep):
        self.board = board
        self.turn = turn
        self.castle = castle
        self.ep = ep

    def copy(self):
        return State(self.board[:], self.turn, self.castle, self.ep)


def gen_pseudo(state, caps_only=False):
    board = state.board
    color = state.turn
    moves = []
    for s in range(64):
        p = board[s]
        if p == "." or color_of(p) != color:
            continue
        low = p.lower()
        f0, r0 = s % 8, s // 8
        if low == "p":
            dr = 1 if color == "w" else -1
            start_rank = 1 if color == "w" else 6
            last_rank = 7 if color == "w" else 0
            r1 = r0 + dr
            if 0 <= r1 < 8:
                one = r1 * 8 + f0
                if board[one] == ".":
                    if r1 == last_rank:
                        for promo in "qrbn":
                            moves.append((s, one, promo))
                    elif not caps_only:
                        moves.append((s, one, None))
                        if r0 == start_rank:
                            two = (r0 + 2 * dr) * 8 + f0
                            if board[two] == ".":
                                moves.append((s, two, None))
            for t in PAWN_CAPS[color][s]:
                if board[t] != "." and color_of(board[t]) != color:
                    if t // 8 == last_rank:
                        for promo in "qrbn":
                            moves.append((s, t, promo))
                    else:
                        moves.append((s, t, None))
                elif state.ep is not None and t == state.ep:
                    moves.append((s, t, "ep"))
        elif low in "nk":
            for t in (KNIGHT_MOVES[s] if low == "n" else KING_MOVES[s]):
                if board[t] != "." and color_of(board[t]) != color:
                    moves.append((s, t, None))
                elif board[t] == "." and not caps_only:
                    moves.append((s, t, None))
            if low == "k" and not caps_only:
                rights = state.castle
                if color == "w" and s == 4:
                    if "K" in rights and board[5] == "." and board[6] == "." and board[7] == "R":
                        if not attacked_by(board, 4, "b") and not attacked_by(board, 5, "b") and not attacked_by(board, 6, "b"):
                            moves.append((s, 6, "O-O"))
                    if "Q" in rights and board[3] == "." and board[2] == "." and board[1] == "." and board[0] == "R":
                        if not attacked_by(board, 4, "b") and not attacked_by(board, 3, "b") and not attacked_by(board, 2, "b"):
                            moves.append((s, 2, "O-O-O"))
                if color == "b" and s == 60:
                    if "k" in rights and board[61] == "." and board[62] == "." and board[63] == "r":
                        if not attacked_by(board, 60, "w") and not attacked_by(board, 61, "w") and not attacked_by(board, 62, "w"):
                            moves.append((s, 62, "O-O"))
                    if "q" in rights and board[59] == "." and board[58] == "." and board[57] == "." and board[56] == "r":
                        if not attacked_by(board, 60, "w") and not attacked_by(board, 59, "w") and not attacked_by(board, 58, "w"):
                            moves.append((s, 58, "O-O-O"))
        else:
            dirs = BISHOP_D if low == "b" else ROOK_D if low == "r" else QUEEN_D
            for t in slide_targets(board, s, dirs):
                if board[t] != "." and color_of(board[t]) != color:
                    moves.append((s, t, None))
                elif board[t] == "." and not caps_only:
                    moves.append((s, t, None))
    return moves


def apply_move(state, move):
    frm, to, extra = move
    st = state.copy()
    board = st.board
    p = board[frm]
    color = state.turn
    other = "b" if color == "w" else "w"
    board[frm] = "."
    if extra == "ep":
        cap_sq = (frm // 8) * 8 + (to % 8)
        board[cap_sq] = "."
    elif extra == "O-O":
        if color == "w":
            board[5] = board[7]
            board[7] = "."
        else:
            board[61] = board[63]
            board[63] = "."
    elif extra == "O-O-O":
        if color == "w":
            board[3] = board[0]
            board[0] = "."
        else:
            board[59] = board[56]
            board[56] = "."
    if extra in ("q", "r", "b", "n"):
        board[to] = extra.upper() if color == "w" else extra
    else:
        board[to] = p
    rights = st.castle
    if p == "K":
        rights = rights.replace("K", "").replace("Q", "")
    elif p == "k":
        rights = rights.replace("k", "").replace("q", "")
    if frm == 0 or to == 0:
        rights = rights.replace("Q", "")
    if frm == 7 or to == 7:
        rights = rights.replace("K", "")
    if frm == 56 or to == 56:
        rights = rights.replace("q", "")
    if frm == 63 or to == 63:
        rights = rights.replace("k", "")
    st.castle = rights if rights else "-"
    st.ep = None
    if p.lower() == "p" and abs(to - frm) == 16:
        st.ep = (frm + to) // 2
    st.turn = other
    return st


def king_square(board, color):
    return board.index("K" if color == "w" else "k")


def in_check(state, color=None):
    color = color or state.turn
    other = "b" if color == "w" else "w"
    return attacked_by(state.board, king_square(state.board, color), other)


def legal_from_pseudo(state, pseudo):
    out = []
    mover = state.turn
    for m in pseudo:
        nxt = apply_move(state, m)
        if not attacked_by(nxt.board, king_square(nxt.board, mover), nxt.turn):
            out.append(m)
    return out


def legal_moves(state):
    return legal_from_pseudo(state, gen_pseudo(state))


def to_uci(move):
    frm, to, extra = move
    promo = extra if extra in ("q", "r", "b", "n") else ""
    return sq_name(frm) + sq_name(to) + promo


PIECE_VAL = {"p": 100, "n": 320, "b": 330, "r": 500, "q": 900, "k": 0}

PAWN_PST = [
    0, 0, 0, 0, 0, 0, 0, 0,
    5, 10, 10, -20, -20, 10, 10, 5,
    5, -5, -10, 0, 0, -10, -5, 5,
    0, 0, 0, 20, 20, 0, 0, 0,
    5, 5, 10, 25, 25, 10, 5, 5,
    10, 10, 20, 30, 30, 20, 10, 10,
    50, 50, 50, 50, 50, 50, 50, 50,
    0, 0, 0, 0, 0, 0, 0, 0,
]
KNIGHT_PST = [
    -50, -40, -30, -30, -30, -30, -40, -50,
    -40, -20, 0, 5, 5, 0, -20, -40,
    -30, 5, 10, 15, 15, 10, 5, -30,
    -30, 0, 15, 20, 20, 15, 0, -30,
    -30, 5, 15, 20, 20, 15, 5, -30,
    -30, 0, 10, 15, 15, 10, 0, -30,
    -40, -20, 0, 0, 0, 0, -20, -40,
    -50, -40, -30, -30, -30, -30, -40, -50,
]
BISHOP_PST = [
    -20, -10, -10, -10, -10, -10, -10, -20,
    -10, 5, 0, 0, 0, 0, 5, -10,
    -10, 10, 10, 10, 10, 10, 10, -10,
    -10, 0, 10, 10, 10, 10, 0, -10,
    -10, 5, 5, 10, 10, 5, 5, -10,
    -10, 0, 5, 10, 10, 5, 0, -10,
    -10, 0, 0, 0, 0, 0, 0, -10,
    -20, -10, -10, -10, -10, -10, -10, -20,
]
ROOK_PST = [
    0, 0, 0, 5, 5, 0, 0, 0,
    -5, 0, 0, 0, 0, 0, 0, -5,
    -5, 0, 0, 0, 0, 0, 0, -5,
    -5, 0, 0, 0, 0, 0, 0, -5,
    -5, 0, 0, 0, 0, 0, 0, -5,
    -5, 0, 0, 0, 0, 0, 0, -5,
    5, 10, 10, 10, 10, 10, 10, 5,
    0, 0, 0, 0, 0, 0, 0, 0,
]
KING_PST = [
    20, 30, 10, 0, 0, 10, 30, 20,
    20, 20, 0, 0, 0, 0, 20, 20,
    -10, -20, -20, -20, -20, -20, -20, -10,
    -20, -30, -30, -40, -40, -30, -30, -20,
    -30, -40, -40, -50, -50, -40, -40, -30,
    -30, -40, -40, -50, -50, -40, -40, -30,
    -30, -40, -40, -50, -50, -40, -40, -30,
    -30, -40, -40, -50, -50, -40, -40, -30,
]
PST = {"p": PAWN_PST, "n": KNIGHT_PST, "b": BISHOP_PST, "r": ROOK_PST, "k": KING_PST}
PST_W = {}
PST_B = {}
for _k, _t in PST.items():
    PST_W[_k] = _t
    PST_B[_k] = [_t[63 - _i] for _i in range(64)]


def evaluate(state):
    board = state.board
    score = 0
    bishops = {"w": 0, "b": 0}
    for s in range(64):
        p = board[s]
        if p == ".":
            continue
        low = p.lower()
        color = color_of(p)
        table = PST_W.get(low) if color == "w" else PST_B.get(low)
        val = PIECE_VAL[low] + (table[s] if table else 0)
        if low == "b":
            bishops[color] += 1
        score += val if color == "w" else -val
    if bishops["w"] >= 2:
        score += 30
    if bishops["b"] >= 2:
        score -= 30
    return score if state.turn == "w" else -score


NODE_BUDGET = 32000
QDEPTH_MAX = 5
nodes = [0]


def order(state, moves):
    board = state.board

    def key(m):
        target = board[m[1]]
        if target != ".":
            return -(PIECE_VAL[target.lower()] * 10 - PIECE_VAL[board[m[0]].lower()])
        return 0

    return sorted(moves, key=key)


def quiescence(state, alpha, beta, qdepth):
    nodes[0] += 1
    if nodes[0] > NODE_BUDGET:
        return evaluate(state)
    check = in_check(state)
    if check:
        candidates = legal_from_pseudo(state, gen_pseudo(state))
        if not candidates:
            return -100000 - qdepth
        if qdepth >= QDEPTH_MAX:
            return evaluate(state)
    else:
        stand_pat = evaluate(state)
        if stand_pat >= beta:
            return beta
        if stand_pat > alpha:
            alpha = stand_pat
        candidates = legal_from_pseudo(state, gen_pseudo(state, True))
        if not candidates:
            return alpha
    for m in order(state, candidates):
        child = apply_move(state, m)
        score = -quiescence(child, -beta, -alpha, qdepth + 1)
        if score >= beta:
            return beta
        if score > alpha:
            alpha = score
        if nodes[0] > NODE_BUDGET:
            break
    return alpha


def negamax(state, depth, alpha, beta):
    nodes[0] += 1
    if nodes[0] > NODE_BUDGET:
        return evaluate(state)
    if depth == 0:
        return quiescence(state, alpha, beta, 0)
    moves = legal_moves(state)
    if not moves:
        return -100000 - depth if in_check(state) else 0
    best = -10 ** 9
    for m in order(state, moves):
        child = apply_move(state, m)
        score = -negamax(child, depth - 1, -beta, -alpha)
        if score > best:
            best = score
        if best > alpha:
            alpha = best
        if alpha >= beta:
            break
        if nodes[0] > NODE_BUDGET:
            break
    return best


def choose(fen, legal_uci):
    board, turn, castle, ep = parse_fen(fen)
    state = State(board, turn, castle, ep)
    legal = legal_moves(state)
    if not legal:
        return legal_uci[0]
    nodes[0] = 0
    best_move = legal[0]
    depth = 1
    while depth <= 6 and nodes[0] <= NODE_BUDGET:
        alpha, beta = -10 ** 9, 10 ** 9
        cur_best = None
        cur_score = -10 ** 9
        complete = True
        for m in order(state, legal):
            if nodes[0] > NODE_BUDGET:
                complete = False
                break
            child = apply_move(state, m)
            score = -negamax(child, depth - 1, -beta, -alpha)
            if score > cur_score:
                cur_score = score
                cur_best = m
            if cur_score > alpha:
                alpha = cur_score
        if complete and cur_best is not None:
            best_move = cur_best
        if not complete:
            break
        depth += 1
    return to_uci(best_move)


def post(path, body):
    req = urllib.request.Request(
        ENV_URL + path,
        data=json.dumps(body).encode(),
        headers={"content-type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req) as res:
            return json.load(res)
    except urllib.error.HTTPError as e:
        sys.exit(f"{path}: HTTP {e.code} {e.read().decode(errors='replace')}")


def main():
    while True:
        g = post("/game", {})
        if g["status"] == "done":
            break
        while g["status"] == "your_move":
            move = choose(g["fen"], g["legal_moves"])
            g = post("/move", {"game": g["game"], "move": move})
        print(f"game {g['game']}: {g['outcome']} by {g['reason']}", file=sys.stderr)
    print(f"done: {g.get('wins')} won, {g.get('draws')} drawn, {g.get('losses')} lost", file=sys.stderr)


if __name__ == "__main__":
    main()
