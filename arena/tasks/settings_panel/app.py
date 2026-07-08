import streamlit as st

st.header("Settings")

st.checkbox("Autosave", key="autosave")
st.checkbox("Dark mode", key="dark_mode")
st.checkbox("Telemetry", key="telemetry")
st.checkbox("Beta features", key="beta_features")
st.checkbox("Notifications", key="notifications")
st.checkbox("Compact view", key="compact_view")

st.slider("Volume", 0, 100, 50, key="volume")
st.slider("Brightness", 0, 100, 50, key="brightness")

st.selectbox("Theme", ["Light", "Dark", "System"], key="theme")
st.selectbox("Language", ["English", "Spanish", "French"], key="language")

st.text_input("Display name", key="display_name")
