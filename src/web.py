"""Streamlit entrypoint placeholder.

The web UI will call the same AgentRuntime as the CLI after it is implemented.
"""


def main() -> None:
    try:
        import streamlit as st
    except ImportError as exc:
        raise RuntimeError("Please install dependencies with: pip install -r requirements.txt") from exc

    st.title("Minimal Agent")
    st.info("Project initialized. Agent runtime is not implemented yet.")


if __name__ == "__main__":
    main()
