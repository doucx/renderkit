import typer

class State:
    """Holds global state like 'quiet mode' to avoid global variables."""
    quiet = False

state = State()

def rich_echo(message: str, **kwargs):
    """A wrapper around typer.echo that respects the quiet flag."""
    if not state.quiet:
        typer.secho(message, **kwargs)