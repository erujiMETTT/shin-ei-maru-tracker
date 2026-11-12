import os
import re
import json
import time
from datetime import datetime, timezone, timedelta
import requests
from bs4 import BeautifulSoup
import pandas as pd

# ===== 設定パラメータ =====
IMO = "9866512"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CSV_PATH = os.path.join(BASE_DIR, "SHIN_EI_MARU_track.csv")
ONLY_SAVE_ON_UPDATE = False  # False: 1時間ごとに毎回記録 / True: 前回と同一座標・AIS時刻ならスキップ

JST = timezone(timedelta(hours=9))


def fetch_vessel_position(imo: str = IMO, retries: int = 3, delay_sec: int = 5) -> dict:
    """
    VesselFinder の船舶ページから現在座標・船速・針路等を取得して辞書で返す。
    """
    url = f"https://www.vesselfinder.com/vessels/details/{imo}"
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
    }

    last_err = None
    for attempt in range(1, retries + 1):
        try:
            resp = requests.get(url, headers=headers, timeout=30)
            resp.raise_for_status()
            break
        except Exception as e:
            last_err = e
            print(f"[Warn] Attempt {attempt}/{retries} failed: {e}")
            if attempt < retries:
                time.sleep(delay_sec)
    else:
        raise RuntimeError(f"Failed to fetch vessel page after {retries} attempts: {last_err}")

    html = resp.text
    soup = BeautifulSoup(html, "html.parser")

    data = {
        "fetched_at_jst": datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S"),
        "imo": imo,
        "mmsi": None,
        "ship_name": None,
        "ais_timestamp_utc": None,
        "latitude": None,
        "longitude": None,
        "sog_kn": None,
        "cog_deg": None,
        "nav_status": None,
    }

    # 1. ページ内の埋め込みJSON (id="djson" 等) からの抽出を試行
    djson_el = soup.find(id="djson")
    if djson_el and djson_el.get("data-json"):
        try:
            vdata = json.loads(djson_el["data-json"])
            data["mmsi"] = vdata.get("mmsi") or data["mmsi"]
            data["ship_name"] = vdata.get("name") or data["ship_name"]
            data["latitude"] = vdata.get("ship_lat") or vdata.get("lat")
            data["longitude"] = vdata.get("ship_lon") or vdata.get("lon")
            data["sog_kn"] = vdata.get("ship_sog") or vdata.get("sog")
            data["cog_deg"] = vdata.get("ship_cog") or vdata.get("cog")
        except json.JSONDecodeError:
            pass

    # 2. テーブル要素 (.aparams 等) からの抽出
    for row in soup.select("table.aparams tr"):
        cells = row.find_all(["td", "th"])
        if len(cells) < 2:
            continue
        label = cells[0].get_text(strip=True).lower()
        val = cells[1].get_text(strip=True)

        if "coordinates" in label and (data["latitude"] is None or data["longitude"] is None):
            m = re.search(r"([0-9.]+)\s*([NS])\s*/\s*([0-9.]+)\s*([EW])", val, re.I)
            if m:
                lat = float(m.group(1)) * (-1 if m.group(2).upper() == "S" else 1)
                lon = float(m.group(3)) * (-1 if m.group(4).upper() == "W" else 1)
                data["latitude"] = lat
                data["longitude"] = lon
        elif "course / speed" in label:
            m = re.search(r"([0-9.]+)\s*°?\s*/\s*([0-9.]+)\s*kn", val, re.I)
            if m:
                if data["cog_deg"] is None:
                    data["cog_deg"] = float(m.group(1))
                if data["sog_kn"] is None:
                    data["sog_kn"] = float(m.group(2))
        elif "navigation status" in label:
            data["nav_status"] = val if val != "-" else None
        elif "imo / mmsi" in label and data["mmsi"] is None:
            m = re.search(r"/\s*(\d{9})", val)
            if m:
                data["mmsi"] = m.group(1)

    # 3. テキスト・メタ情報からのフォールバック抽出
    if data["latitude"] is None or data["longitude"] is None:
        m_coord = re.search(
            r"coordinates\s+([0-9.]+)\s*([NS])\s*/\s*([0-9.]+)\s*([EW])",
            html,
            re.I,
        )
        if m_coord:
            data["latitude"] = float(m_coord.group(1)) * (-1 if m_coord.group(2).upper() == "S" else 1)
            data["longitude"] = float(m_coord.group(3)) * (-1 if m_coord.group(4).upper() == "W" else 1)

    # AIS受信時刻 (id="last_report_ts" または data-timestamp 等)
    ts_el = soup.find(id="last_report_ts") or soup.find(attrs={"data-timestamp": True})
    if ts_el:
        ts_val = ts_el.get("data-timestamp") or ts_el.get_text(strip=True)
        if ts_val and str(ts_val).isdigit():
            dt_utc = datetime.fromtimestamp(int(ts_val), tz=timezone.utc)
            data["ais_timestamp_utc"] = dt_utc.strftime("%Y-%m-%d %H:%M:%S")
        else:
            data["ais_timestamp_utc"] = ts_val

    if data["ship_name"] is None:
        h1 = soup.find("h1")
        if h1:
            data["ship_name"] = h1.get_text(strip=True)

    return data


def append_to_csv(record: dict, csv_path: str = CSV_PATH, only_on_update: bool = ONLY_SAVE_ON_UPDATE) -> bool:
    """
    取得した1件のレコードをCSVに追記する。
    """
    df_new = pd.DataFrame([record])

    if os.path.exists(csv_path) and os.path.getsize(csv_path) > 0:
        if only_on_update:
            df_existing = pd.read_csv(csv_path)
            if not df_existing.empty:
                last = df_existing.iloc[-1]
                same_lat = pd.notna(last.get("latitude")) and last.get("latitude") == record.get("latitude")
                same_lon = pd.notna(last.get("longitude")) and last.get("longitude") == record.get("longitude")
                same_ts = str(last.get("ais_timestamp_utc")) == str(record.get("ais_timestamp_utc"))
                if same_lat and same_lon and same_ts:
                    return False
        df_new.to_csv(csv_path, mode="a", header=False, index=False, encoding="utf-8-sig")
    else:
        df_new.to_csv(csv_path, mode="w", header=True, index=False, encoding="utf-8-sig")

    return True


if __name__ == "__main__":
    record = fetch_vessel_position(IMO)
    saved = append_to_csv(record, CSV_PATH, only_on_update=ONLY_SAVE_ON_UPDATE)
    status = "Saved" if saved else "Skipped (no update)"
    print(
        f"[{record['fetched_at_jst']}] {status} | "
        f"Lat: {record['latitude']}, Lon: {record['longitude']}, "
        f"SOG: {record['sog_kn']} kn, COG: {record['cog_deg']} deg"
    )
