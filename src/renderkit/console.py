import typer

class State:
    """Holds global state like 'quiet mode' to avoid global variables."""
    quiet = False
    debug = False

state = State()

def rich_echo(message: str, **kwargs):
    """A wrapper around typer.echo that respects the quiet flag and prints to stderr."""
    if not state.quiet:
        # 所有常规日志输出到 stderr
        typer.secho(message, err=True, **kwargs)

def rich_debug(message: str, **kwargs):
    """Prints a debug message only if debug mode is enabled."""
    if state.debug:
        # 调试信息也输出到 stderr，并带有标记和不同颜色
        typer.secho(f"[DEBUG] {message}", err=True, fg=typer.colors.YELLOW, **kwargs)