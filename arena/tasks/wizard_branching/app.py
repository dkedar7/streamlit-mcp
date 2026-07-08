import streamlit as st

st.title("Setup wizard")

# Each step reveals the next: the widget tree is a function of state the agent controls, so the
# agent must re-introspect after every action (a widget it needs may not exist yet).
st.radio("Mode", ["Basic", "Advanced"], key="mode")

if st.session_state.get("mode") == "Advanced":
    st.number_input("Threshold", min_value=0, max_value=100, value=0, key="threshold")

    if st.session_state.get("threshold", 0) >= 50:
        st.checkbox("Confirm high threshold", key="confirmed")

if st.session_state.get("confirmed"):
    st.subheader("Configured.")
