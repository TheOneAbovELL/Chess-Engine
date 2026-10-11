"""UCI protocol tests.

Two layers:
* in-process tests drive :class:`UciEngine` with an in-memory stream;
* subprocess tests launch ``python -m chesslab_engine`` and talk to it through
  python-chess's UCI client, the same path the ChessLab backend uses.
"""

import io
import sys
import time

import chess
import chess.engine
import pytest

from chesslab_engine.uci import UciEngine

ENGINE_CMD = [sys.executable, "-m", "chesslab_engine"]


def run_commands(*commands: str, wait: float = 0.0) -> list[str]:
    out = io.StringIO()
    engine = UciEngine(out)
    for cmd in commands:
        engine.handle(cmd)
        if cmd.startswith("go"):
            time.sleep(wait)
    engine.stop_search()
    return out.getvalue().splitlines()


def test_uci_handshake_lists_options() -> None:
    lines = run_commands("uci")
    assert lines[0].startswith("id name ChessLab Engine")
    assert lines[-1] == "uciok"
    assert any("option name Hash type spin" in line for line in lines)
    assert any("option name UseQuiescence type check" in line for line in lines)


def test_isready_and_unknown_command() -> None:
    lines = run_commands("isready", "frobnicate")
    assert lines[0] == "readyok"
    assert lines[1].startswith("info string unknown command")


def test_malformed_input_does_not_crash() -> None:
    lines = run_commands(
        "position fen this-is-not-a-fen",
        "position startpos moves e2e5",
        "setoption name Hash value banana",
        "go depth 1",
        wait=0.5,
    )
    errors = [line for line in lines if line.startswith("info string error")]
    assert len(errors) == 3
    assert any(line.startswith("bestmove ") for line in lines)


def test_go_depth_reports_info_and_bestmove() -> None:
    lines = run_commands("position startpos moves e2e4", "go depth 3", wait=2.0)
    infos = [line for line in lines if line.startswith("info depth")]
    assert [int(line.split()[2]) for line in infos] == [1, 2, 3]
    best = [line for line in lines if line.startswith("bestmove")]
    assert len(best) == 1
    move = chess.Move.from_uci(best[0].split()[1])
    board = chess.Board()
    board.push_uci("e2e4")
    assert move in board.legal_moves


def test_bestmove_0000_when_no_legal_moves() -> None:
    lines = run_commands("position fen 7k/6Q1/6K1/8/8/8/8/8 b - - 0 1", "go depth 2", wait=0.3)
    assert "bestmove 0000" in lines


# ---------------------------------------------------------------- subprocess


@pytest.fixture()
def engine() -> chess.engine.SimpleEngine:
    eng = chess.engine.SimpleEngine.popen_uci(ENGINE_CMD, timeout=30)
    yield eng
    eng.quit()


def test_subprocess_identifies(engine: chess.engine.SimpleEngine) -> None:
    assert engine.id["name"].startswith("ChessLab Engine")
    assert "MultiPV" in engine.options


def test_subprocess_analyse_multipv(engine: chess.engine.SimpleEngine) -> None:
    infos = engine.analyse(chess.Board(), chess.engine.Limit(depth=3), multipv=2)
    assert len(infos) == 2
    assert infos[0]["pv"][0] != infos[1]["pv"][0]
    assert infos[0]["depth"] == 3
    assert "score" in infos[0] and "nodes" in infos[0]


def test_subprocess_reports_mate_score(engine: chess.engine.SimpleEngine) -> None:
    board = chess.Board("6k1/5ppp/8/8/8/8/8/R5K1 w - - 0 1")
    info = engine.analyse(board, chess.engine.Limit(depth=3))
    assert info["score"].white() == chess.engine.Mate(1)


def test_subprocess_play_with_time_limit(engine: chess.engine.SimpleEngine) -> None:
    board = chess.Board()
    start = time.perf_counter()
    result = engine.play(board, chess.engine.Limit(time=0.3))
    assert result.move in board.legal_moves
    assert time.perf_counter() - start < 3


def test_subprocess_infinite_analysis_can_be_stopped(engine: chess.engine.SimpleEngine) -> None:
    with engine.analysis(chess.Board()) as analysis:
        time.sleep(0.5)
        analysis.stop()
        best = analysis.wait()
    assert best.move in chess.Board().legal_moves


def test_subprocess_feature_toggle_options(engine: chess.engine.SimpleEngine) -> None:
    engine.configure({"UseNullMove": False, "EvalMobility": False, "Hash": 8})
    result = engine.play(chess.Board(), chess.engine.Limit(depth=2))
    assert result.move in chess.Board().legal_moves
