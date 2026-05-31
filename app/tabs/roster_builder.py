"""Tab 1: Roster Builder — placeholder for the sprint."""
import streamlit as st


def render() -> None:
    st.subheader("Roster Builder")
    st.caption("Construct an optimal lineup vs. a specific opponent. In work.")
    st.info(
        "**In work.** This tab will take a team and an opponent and return a "
        "recommended starting lineup with role assignments, projected matchup "
        "advantage, and a 2–3 sentence strategic summary."
    )
    with st.expander("Planned inputs"):
        st.markdown(
            "- Team selector (all 30 MLB teams)\n"
            "- Opponent selector (all 30 MLB teams)\n"
            "- Max payroll for 2025 (pre-filled with current team payroll)\n"
        )
    with st.expander("Planned outputs"):
        st.markdown(
            "- Lineup card: 9 batting slots + 5 rotation slots + closer\n"
            "- Per-player role: power, contact, speed, defense, ace, etc.\n"
            "- Projected matchup advantage vs. the opponent's pitching/lineup\n"
            "- LLM-generated 2–3 sentence strategic recommendation\n"
        )
