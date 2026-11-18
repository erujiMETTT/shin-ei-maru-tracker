import os
import math
import argparse
import pandas as pd
import matplotlib.pyplot as plt

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_CSV_PATH = os.path.join(BASE_DIR, "SHIN_EI_MARU_track.csv")
DEFAULT_OUT_PATH = os.path.join(BASE_DIR, "SHIN_EI_MARU_track.png")


def load_track(csv_path: str) -> pd.DataFrame:
    """
    CSV から位置情報を読み込み、有効な座標行を時刻順に整列して返す。
    """
    if not os.path.exists(csv_path):
        raise FileNotFoundError(f"CSV file not found: {csv_path}")

    df = pd.read_csv(csv_path)
    if df.empty:
        return df

    df["latitude"] = pd.to_numeric(df["latitude"], errors="coerce")
    df["longitude"] = pd.to_numeric(df["longitude"], errors="coerce")
    if "sog_kn" in df.columns:
        df["sog_kn"] = pd.to_numeric(df["sog_kn"], errors="coerce")

    df = df.dropna(subset=["latitude", "longitude"]).copy()
    if df.empty:
        return df

    if "fetched_at_jst" in df.columns:
        df["fetched_at_jst_dt"] = pd.to_datetime(df["fetched_at_jst"], errors="coerce")
        df = df.sort_values("fetched_at_jst_dt").reset_index(drop=True)

    return df


def plot_track(csv_path: str, out_path: str, show: bool = True) -> None:
    """
    航路を matplotlib で描画し、画像として保存する。
    """
    df = load_track(csv_path)
    if df.empty:
        print("No valid coordinate records found in CSV.")
        return

    lats = df["latitude"].to_numpy()
    lons = df["longitude"].to_numpy()

    fig, ax = plt.subplots(figsize=(9, 8), dpi=150)

    # 航路の軌跡線
    ax.plot(lons, lats, color="steelblue", linewidth=1.8, alpha=0.85, zorder=2, label="Track")

    # 船速 (sog_kn) があれば色で表現、なければ単色でプロット
    has_sog = "sog_kn" in df.columns and df["sog_kn"].notna().any()
    if has_sog:
        sc = ax.scatter(
            lons,
            lats,
            c=df["sog_kn"],
            cmap="viridis",
            s=30,
            zorder=3,
            edgecolors="white",
            linewidths=0.4,
        )
        cbar = fig.colorbar(sc, ax=ax, pad=0.02, shrink=0.85)
        cbar.set_label("SOG [kn]")
    else:
        ax.scatter(lons, lats, color="steelblue", s=25, zorder=3)

    # 開始点・最新点のマーカー
    ax.scatter(
        lons[0],
        lats[0],
        color="limegreen",
        edgecolors="black",
        s=90,
        marker="o",
        zorder=4,
        label=f"Start ({df['fetched_at_jst'].iloc[0]})" if "fetched_at_jst" in df.columns else "Start",
    )
    ax.scatter(
        lons[-1],
        lats[-1],
        color="crimson",
        edgecolors="black",
        s=130,
        marker="*",
        zorder=5,
        label=f"Latest ({df['fetched_at_jst'].iloc[-1]})" if "fetched_at_jst" in df.columns else "Latest",
    )

    # 緯度に応じた縦横比補正（経度1度と緯度1度の距離比）
    mean_lat_rad = math.radians(float(lats.mean()))
    cos_lat = max(math.cos(mean_lat_rad), 1e-6)
    ax.set_aspect(1.0 / cos_lat)

    # 表示範囲に余白を追加
    lon_span = float(lons.max() - lons.min())
    lat_span = float(lats.max() - lats.min())
    pad_lon = max(lon_span * 0.12, 0.02)
    pad_lat = max(lat_span * 0.12, 0.02)
    ax.set_xlim(float(lons.min()) - pad_lon, float(lons.max()) + pad_lon)
    ax.set_ylim(float(lats.min()) - pad_lat, float(lats.max()) + pad_lat)

    ship_name = (
        df["ship_name"].dropna().iloc[-1]
        if "ship_name" in df.columns and df["ship_name"].notna().any()
        else "SHIN EI MARU"
    )
    ax.set_title(f"{ship_name} Track (n={len(df)})", fontsize=13, pad=10)
    ax.set_xlabel("Longitude [deg]")
    ax.set_ylabel("Latitude [deg]")
    ax.grid(True, linestyle="--", alpha=0.5)
    ax.legend(loc="best", fontsize=9)

    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    print(f"Saved track plot to: {out_path} ({len(df)} points)")

    if show:
        plt.show()
    else:
        plt.close(fig)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="SHIN_EI_MARU_track.csv から航路を matplotlib で描画する")
    parser.add_argument("--csv", default=DEFAULT_CSV_PATH, help="入力 CSV ファイルのパス")
    parser.add_argument("--out", default=DEFAULT_OUT_PATH, help="出力 PNG ファイルのパス")
    parser.add_argument("--no-show", action="store_true", help="画面表示せず PNG 保存のみ行う")
    args = parser.parse_args()

    plot_track(csv_path=args.csv, out_path=args.out, show=not args.no_show)
