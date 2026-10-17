"""Fixture app with no *supported* widgets — a chat app, the exact class of #150.

st.chat_input is unsupported in v1, so this app drives nothing: bare `inspect` on it
used to print 0 bytes at exit 0, while --json reported {"widgets": []} and --layout
printed the outputs plus the `unsupported:` section explaining why.
"""

import streamlit as st

st.title("Chat Assistant")
msg = st.chat_input("Ask me anything")
if msg:
    st.write(f"You said: {msg}")
