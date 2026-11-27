import os
import json
import math
import tempfile
import argparse
import requests
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.patches import Polygon
from matplotlib.collections import PatchCollection

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_CSV_PATH = os.path.join(BASE_DIR, "SHIN_EI_MARU_track.csv")
DEFAULT_OUT_PATH = os.path.join(BASE_DIR, "SHIN_EI_MARU_track.png")

JAPAN_GEOJSON_URL = (
    "https://raw.githubusercontent.com/dataofjapan/land/master/japan.geojson"
)
JAPAN_GEOJSON_CACHE = os.path.join(tempfile.gettempdir(), "shin_ei_maru_jpn_detailed.geojson")


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
    df = df.dropna(subset=["latitude", "longitude"]).copy()
    if df.empty:
        return df

    if "fetched_at_jst" in df.columns:
        df["fetched_at_jst_dt"] = pd.to_datetime(df["fetched_at_jst"], errors="coerce")
        df = df.sort_values("fetched_at_jst_dt").reset_index(drop=True)

    return df


def load_japan_polygons() -> list[Polygon]:
    """
    簡易的な日本地図のポリゴン（GeoJSON）を取得・キャッシュして matplotlib の Polygon リストを返す。
    """
    geojson_data = None
    if os.path.exists(JAPAN_GEOJSON_CACHE):
        try:
            with open(JAPAN_GEOJSON_CACHE, "r", encoding="utf-8") as f:
                geojson_data = json.load(f)
        except Exception:
            geojson_data = None

    if geojson_data is None:
        try:
            resp = requests.get(JAPAN_GEOJSON_URL, timeout=15)
            resp.raise_for_status()
            geojson_data = resp.json()
            with open(JAPAN_GEOJSON_CACHE, "w", encoding="utf-8") as f:
                json.dump(geojson_data, f)
        except Exception as e:
            print(f"[Warn] 日本地図データの取得に失敗しました（航路のみ描画します）: {e}")
            return []

    polygons: list[Polygon] = []
    features = geojson_data.get("features", [])
    for feat in features:
        geom = feat.get("geometry") or {}
        gtype = geom.get("type")
        coords = geom.get("coordinates") or []

        if gtype == "Polygon":
            if coords:
                polygons.append(Polygon(coords[0], closed=True))
        elif gtype == "MultiPolygon":
            for poly_coords in coords:
                if poly_coords:
                    polygons.append(Polygon(poly_coords[0], closed=True))

    return polygons


def plot_track(csv_path: str, out_path: str, show: bool = True) -> None:
    """
    日本地図を背景に、航路の実線のみを matplotlib で描画して保存する。
    """
    df = load_track(csv_path)
    if df.empty:
        print("No valid coordinate records found in CSV.")
        return

    lats = df["latitude"].to_numpy()
    lons = df["longitude"].to_numpy()

    fig, ax = plt.subplots(figsize=(9, 8), dpi=150)
    ax.set_facecolor("#eef5fb")

    # 背景の詳細日本地図（都道府県・海岸線）
    japan_polys = load_japan_polygons()
    if japan_polys:
        pc = PatchCollection(
            japan_polys,
            facecolor="#eae6df",
            edgecolor="#666666",
            linewidth=0.5,
            zorder=1,
        )
        ax.add_collection(pc)

    # 航路の実線のみ描画
    ax.plot(
        lons,
        lats,
        color="tab:blue",
        linewidth=2.0,
        linestyle="-",
        zorder=2,
        label="Track",
    )

    # 緯度に応じた縦横比補正（経度1度と緯度1度の距離比）
    mean_lat_rad = math.radians(float(lats.mean()))
    cos_lat = max(math.cos(mean_lat_rad), 1e-6)
    ax.set_aspect(1.0 / cos_lat)

    # 表示範囲に余白を追加
    lon_span = float(lons.max() - lons.min())
    lat_span = float(lats.max() - lats.min())
    pad_lon = max(lon_span * 0.15, 0.1)
    pad_lat = max(lat_span * 0.15, 0.1)
    ax.set_xlim(float(lons.min()) - pad_lon, float(lons.max()) + pad_lon)
    ax.set_ylim(float(lats.min()) - pad_lat, float(lats.max()) + pad_lat)

    ship_name = (
        df["ship_name"].dropna().iloc[-1]
        if "ship_name" in df.columns and df["ship_name"].notna().any()
        else "SHIN EI MARU"
    )
    ax.set_title(f"{ship_name} Track", fontsize=13, pad=10)
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
