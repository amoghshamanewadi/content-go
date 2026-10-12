"""Generate only three premium-partner charts. Shares use the original global totals."""
# Use Path to build file locations reliably on Windows.
from pathlib import Path
# Use pandas to load, filter, group, and rank the data.
import pandas as pd
# Use Matplotlib to create and save the charts.
import matplotlib.pyplot as plt
# Locate the project folder relative to this script.
ROOT = Path(__file__).resolve().parents[1]
# Save premium charts in a separate folder to avoid overwriting open original charts.
FIGURES_PATH = ROOT / "outputs" / "figures" / "premium"
# Select learning-minute totals and global shares for partner aggregation.
METRIC_COLUMNS = ["learning_minutes_capped_new", "learning_minutes_capped_old", "pct_of_total_new_learning_minutes", "pct_of_total_old_learning_minutes"]


# Sum the selected metrics by the requested grouping columns; preserve all-missing totals.
def aggregate_metrics(dataset: pd.DataFrame, dimensions: list[str]) -> pd.DataFrame:
    """Sum observed groups only, preserving unknown groups and missing metrics."""
    # Keep observed groups, sum with missing totals preserved, then sort and renumber rows.
    return (
        dataset.groupby(dimensions, as_index=False, dropna=False, observed=True)[METRIC_COLUMNS]
        .sum(min_count=1)
        .sort_values("learning_minutes_capped_new", ascending=False, na_position="last")
        .reset_index(drop=True)
    )

# Produce one aggregate row per content partner.
def aggregate_by_content_partner(dataset: pd.DataFrame) -> pd.DataFrame:
    return aggregate_metrics(dataset, ["cp_portal_id"])

# Compare old and new global shares and calculate premium-partner ranks.
def compare_partner_rankings(partners: pd.DataFrame) -> pd.DataFrame:
    """Compare shares in percentage points; positive rank change means improvement."""
    result = partners.copy()
    # Select new-calculation shares.
    new = result["pct_of_total_new_learning_minutes"]
    # Select old-calculation shares.
    old = result["pct_of_total_old_learning_minutes"]
    # Rank partners by share, using the same rank for ties.
    result["new_rank"] = new.rank(method="min", ascending=False).astype("Int64")
    # Rank partners by share, using the same rank for ties.
    result["old_rank"] = old.rank(method="min", ascending=False).astype("Int64")
    # Subtract old share from new share to get the percentage-point change.
    result["share_change_pp"] = new - old
    # Subtract new rank from old rank; positive values mean an improvement.
    result["rank_improvement"] = result["old_rank"] - result["new_rank"]
    return result.sort_values("new_rank", na_position="last").reset_index(drop=True)

# Save only the three requested premium-partner charts.
def plot_partner_comparison(comparison: pd.DataFrame, top_n: int = 20) -> None:
    """Save only premium rankings, share changes, and rank movement."""
    # Create the output folder if it does not exist.
    FIGURES_PATH.mkdir(parents=True, exist_ok=True)
    # Create side-by-side panels for old and new partner rankings.
    fig, axes = plt.subplots(1, 2, figsize=(16, 9))
    # Draw the old calculation in grey and the new calculation in blue.
    for ax, calculation, color in zip(axes, ("old", "new"), ("#64748b", "#0891b2")):
        # Choose the share column for the current calculation.
        column = f"pct_of_total_{calculation}_learning_minutes"
        # Select the highest-share partners and order them for plotting.
        top = comparison.dropna(subset=[column]).nlargest(top_n, column).iloc[::-1]
        # Draw the bars for the selected partners.
        bars = ax.barh(top["cp_portal_id"].astype(str), top[column].astype(float), color=color)
        # Display values beside the bars.
        ax.bar_label(bars, fmt="%.2f%%", padding=3, fontsize=8)
        # Set chart titles and axis labels.
        ax.set(title=f"Top {top_n} premium partners — {calculation} calculation",
               xlabel="Share of all learning minutes (%)", ylabel="cp_portal_id")
        # Leave room for chart labels.
        ax.margins(x=0.18)
    # Adjust spacing so chart labels fit.
    fig.tight_layout()
    # Save the chart as a PNG file.
    fig.savefig(FIGURES_PATH / "partner_share_rankings.png", dpi=180)
    # Release the figure after saving it.
    plt.close(fig)

    # Keep only partners with both old and new shares. Missing old shares must not be treated as zero.
    comparable = comparison.dropna(subset=["pct_of_total_new_learning_minutes", "pct_of_total_old_learning_minutes"]).copy()
    # Select and order the largest absolute share changes.
    movers = comparable.loc[comparable["share_change_pp"].abs().nlargest(top_n).index]
    # Select and order the largest absolute share changes.
    movers = movers.sort_values("share_change_pp")
    fig, ax = plt.subplots(figsize=(12, 9))
    # Draw the bars for the selected partners.
    bars = ax.barh(movers["cp_portal_id"].astype(str), movers["share_change_pp"].astype(float),
                   color=["#0891b2" if value >= 0 else "#e76f51" for value in movers["share_change_pp"]])
    # Display values beside the bars.
    ax.bar_label(bars, fmt="%+.3f", padding=4)
    # Mark zero to separate increases from decreases.
    ax.axvline(0, color="black", linewidth=0.8)
    # Set chart titles and axis labels.
    ax.set(title=f"Largest {top_n} share changes — premium partners with both calculations",
           xlabel="New share − old share (percentage points)", ylabel="cp_portal_id")
    # Leave room for chart labels.
    ax.margins(x=0.2)
    # Adjust spacing so chart labels fit.
    fig.tight_layout()
    # Save the chart as a PNG file.
    fig.savefig(FIGURES_PATH / "partner_share_changes.png", dpi=180)
    # Release the figure after saving it.
    plt.close(fig)

    # Select comparable partners in either premium top-20 ranking.
    leaders = comparable.loc[comparable["new_rank"].le(top_n) | comparable["old_rank"].le(top_n)]
    fig, ax = plt.subplots(figsize=(12, max(8, len(leaders) * 0.3)))
    # Draw one old-to-new rank connection for each selected partner.
    for _, row in leaders.iterrows():
        # Colour rank improvements blue, declines orange, and unchanged ranks grey.
        color = "#0891b2" if row["rank_improvement"] > 0 else "#e76f51" if row["rank_improvement"] < 0 else "#64748b"
        # Connect each partner's old rank to its new rank.
        ax.plot([0, 1], [row["old_rank"], row["new_rank"]], "o-", color=color, alpha=0.7)
        # Label the partner identifier and rank beside the line endpoint.
        ax.text(-0.03, row["old_rank"], f"{row['cp_portal_id']} ({row['old_rank']})", ha="right", va="center", fontsize=8)
        # Label the partner identifier and rank beside the line endpoint.
        ax.text(1.03, row["new_rank"], f"{row['cp_portal_id']} ({row['new_rank']})", ha="left", va="center", fontsize=8)
    # Name the old and new rank positions.
    ax.set_xticks([0, 1], ["Old rank", "New rank"])
    # Leave horizontal room for the partner labels.
    ax.set_xlim(-0.65, 1.65)
    # Place rank one at the top of the chart.
    ax.invert_yaxis()
    # Set chart titles and axis labels.
    ax.set(title=f"Premium rank movement — comparable partners in either top {top_n}", ylabel="Premium rank (1 = highest share)")
    # Adjust spacing so chart labels fit.
    fig.tight_layout()
    # Save the chart as a PNG file.
    fig.savefig(FIGURES_PATH / "partner_rank_movement.png", dpi=180)
    # Release the figure after saving it.
    plt.close(fig)



# Run this section only when the script is executed directly.
if __name__ == "__main__":
    # Read only required columns and preserve missing values with nullable types.
    df = pd.read_csv(ROOT / "outputs" / "tables" / "All_ds_joined.csv", usecols=["cp_portal_id", "cp_is_premium", *METRIC_COLUMNS], dtype={"cp_portal_id": "string", "cp_is_premium": "boolean", **{column: "Float64" for column in METRIC_COLUMNS}}, true_values=["true"], false_values=["false"])
    # Keep rows explicitly marked premium; exclude false and unknown premium status.
    df = df.loc[df["cp_is_premium"].eq(True).fillna(False)].copy()
    # Aggregate premium partners and calculate old/new shares, ranks, and changes.
    cp_comparison_df = compare_partner_rankings(aggregate_by_content_partner(df))
    # Generate the three requested PNG charts.
    plot_partner_comparison(cp_comparison_df)
    # Show progress or results in the terminal.
    print(f"Generated the three requested charts for {len(cp_comparison_df):,} premium partners in {FIGURES_PATH}")
