# engines/

Place chess engine executables here. ChessLab looks for `stockfish*` executables
in this folder (recursively) when `CHESSLAB_STOCKFISH_PATH` is not set and no
`stockfish` is on your PATH.

Install the official Stockfish release with:

    powershell -ExecutionPolicy Bypass -File scripts\install_stockfish.ps1

Everything in this folder except this README is ignored by Git: engine binaries
are large, platform-specific and GPL-licensed, so they are not committed.
