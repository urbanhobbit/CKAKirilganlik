# app.py
# pip install streamlit pandas geopandas pydeck openpyxl

import re
import os
import requests
from difflib import get_close_matches

import numpy as np
import pandas as pd
import geopandas as gpd
import streamlit as st
import pydeck as pdk
import plotly.graph_objects as go
import plotly.express as px

# -------------------- Paths --------------------
XLSX_MAIN = "data/Endeksler.xlsx"
XLSX_SUB = "data/Alt Endeksler.xlsx"

# Tercih: GeoJSON (en pratik)
GEO_PATH = "data/adana_vulnerability.geojson"  # elindeki dosya
# Alternatif: SHP (geojson yoksa aç)
# GEO_PATH = "adana_mersin.shp"

def ensure_file(local_path, secret_key):
    """
    Ensures the file exists locally. 
    1. If it exists, returns local_path.
    2. If not, attempts to download from st.secrets["data_urls"][secret_key].
    """
    if os.path.exists(local_path):
        return local_path
    
    # Check secrets
    if "data_urls" not in st.secrets or secret_key not in st.secrets["data_urls"]:
        st.error(f"Dosya bulunamadı ve indirme linki tanımlanmamış: {local_path} (Secret: {secret_key})")
        st.stop()
        
    url = st.secrets["data_urls"][secret_key]
    
    # Try creating directory if missing
    os.makedirs(os.path.dirname(local_path), exist_ok=True)
    
    with st.spinner(f"Veri indiriliyor: {local_path}..."):
        try:
            r = requests.get(url)
            r.raise_for_status()
            with open(local_path, "wb") as f:
                f.write(r.content)
        except Exception as e:
            st.error(f"Veri indirilirken hata oluştu: {e}")
            st.stop()
            
    return local_path

# -------------------- Column name helpers --------------------
def clean_cols(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [str(c).strip() for c in df.columns]
    return df

def normalize_text(s: str) -> str:
    s = str(s).strip().lower()
    # Türkçe karakterler için kaba normalizasyon (yakın eşleşmeyi kolaylaştırır)
    s = (s.replace("ç", "c").replace("ğ", "g").replace("ı", "i").replace("ö", "o").replace("ş", "s").replace("ü", "u"))
    s = re.sub(r"\s+", " ", s)
    return s

def find_col(df: pd.DataFrame, wanted: str, aliases: list[str]) -> str:
    cols = list(df.columns)

    # 1) birebir
    if wanted in cols:
        return wanted

    # 2) alias birebir
    for a in aliases:
        if a in cols:
            return a

    # 3) normalize ederek yakın eşleşme
    wanted_n = normalize_text(wanted)
    col_map = {c: normalize_text(c) for c in cols}

    # önce normalize edilmiş birebir
    for c, cn in col_map.items():
        if cn == wanted_n:
            return c

    # difflib yakın eşleşme (normalize metin üzerinde)
    inv = {v: k for k, v in col_map.items()}
    m = get_close_matches(wanted_n, list(inv.keys()), n=1, cutoff=0.70)
    if m:
        return inv[m[0]]

    # 4) regex ipucu
    pat = None
    if "cekirdek" in wanted_n or "core" in wanted_n:
        pat = re.compile(r"(cekir|çekir|core)", re.I)
    elif "genislet" in wanted_n or "extended" in wanted_n:
        pat = re.compile(r"(genis|geniş|extended|ext)", re.I)
    elif "ilce" in wanted_n:
        pat = re.compile(r"(ilce|ilçe)", re.I)
    elif "mahalle" in wanted_n:
        pat = re.compile(r"(mahalle|koy|köy)", re.I)

    if pat is not None:
        for c in cols:
            if pat.search(str(c)):
                return c

    print(f"DEBUG: Wanted: {wanted}")
    print(f"DEBUG: Available columns: {cols}")
    st.error(f"Kolon bulunamadı: {wanted}")
    st.write("Mevcut kolonlar:", cols)
    st.text(f"Aranan (raw): {wanted}")
    st.text(f"Aranan (norm): {normalize_text(wanted)}")
    st.stop()

# -------------------- Numeric helpers --------------------
def minmax01(s: pd.Series) -> pd.Series:
    s = pd.to_numeric(s, errors="coerce")
    mn, mx = s.min(skipna=True), s.max(skipna=True)
    if pd.isna(mn) or pd.isna(mx) or mn == mx:
        return pd.Series(np.nan, index=s.index)
    return (s - mn) / (mx - mn)

def colors_from_01(values: np.ndarray) -> np.ndarray:
    """
    v in [0,1] -> RGBA
    Palette: Blue -> Light Blue -> Yellow -> Orange -> Red
    Mimics 'Vulnerability Index' style.
    """
    v = np.clip(values.astype(float), 0, 1)
    
    # Define interpolation points (0.0 to 1.0)
    # Stops: Lower(0.0) -> Low(0.25) -> Moderate(0.5) -> High(0.75) -> Higher(1.0)
    x_pts = [0.0, 0.25, 0.50, 0.75, 1.0]
    
    # Colors RGB
    # Blue: [44, 123, 182]
    # L.Blue: [171, 217, 233] 
    # Yellow: [255, 255, 191]
    # Orange: [253, 174, 97]
    # Red: [215, 25, 28]
    
    r_pts = [44,  171, 255, 253, 215]
    g_pts = [123, 217, 255, 174, 25]
    b_pts = [182, 233, 191, 97,  28]
    
    r = np.interp(v, x_pts, r_pts)
    g = np.interp(v, x_pts, g_pts)
    b = np.interp(v, x_pts, b_pts)
    a = np.full_like(r, 180)
    
    return np.vstack([r, g, b, a]).T.astype(int)

# -------------------- Data loaders --------------------
# -------------------- 1. Core Structures & Metadata --------------------

class MetricMetadata:
    def __init__(self, col_name, label=None, group=None, scale_type="raw"):
        self.col_name = col_name
        self.label = label or col_name
        self.group = group or "Genel"  # Ana Endeksler, Alt Endeksler, Kentsel, Kırsal vb.
        self.scale_type = scale_type   # 'raw', '0_1', 'pctl'
    
    @property
    def is_normalized_default(self):
        return self.scale_type == "0_1"

def build_metric_metadata(df):
    """
    Excel kolonlarından otomatik metadata çıkarır.
    Gelişmiş versiyonda burası elle tanımlı bir sözlükten de beslenebilir.
    Şimdilik heuristik yapı korunuyor ama bu sınıfa map ediliyor.
    """
    meta = {}
    cols = [str(c).strip() for c in df.columns if c not in ["MAHALLEKAYITNO", "İLADI", "İLÇEADI", "MAHALLEKÖYADI", "MAHALLEKOYADI"]]
    
    for c in cols:
        group = "Diğer"
        c_lower = normalize_text(c)
        
        if "kentsel" in c_lower:
            group = "Kentsel Kırılganlık"
        elif "kirsal" in c_lower:
            group = "Kırsal Kırılganlık"
        elif "alt endeks" in c_lower or "duzeltilmis" in c_lower:
            group = "Alt Endeksler"
        elif "endeks" in c_lower:
             group = "Ana Endeksler" # Kırılganlık Endeksi vb.
        
        # Etiket temizliği
        label = c.replace("Skor", "").replace("Düzeltilmiş", "").strip()
        
        meta[c] = MetricMetadata(
            col_name=c,
            label=label,
            group=group
        )
    return meta

def clean_id(val):
    """Canonicalize IDs: 1701.0 -> '1701'"""
    try:
        return str(int(float(val)))
    except:
        return str(val).strip()

def prepare_metric_data(df, metric_meta: MetricMetadata):
    """
    Tek bir fonksiyon tüm temizlik, normalizasyon ve filtre hazırlığını yapar.
    Returns: Series (cleaned numeric), Series (normalized 0-1)
    """
    col = metric_meta.col_name
    if col not in df.columns:
        return None, None
    
    # 1. Decimal Cleaning (Tr -> Eng)
    series = df[col].astype(str).str.replace(",", ".").str.strip()
    series = pd.to_numeric(series, errors='coerce')
    
    # 2. Normalization
    # Negatif değerleri veya 0-1 dışı değerleri handle eder
    mn, mx = series.min(), series.max()
    if pd.isna(mn) or pd.isna(mx) or mn == mx:
        norm = pd.Series(np.nan, index=series.index)
    else:
        norm = (series - mn) / (mx - mn)
        
    return series, norm

# -------------------- Data Loaders (Optimized) --------------------
@st.cache_data
def load_data_central(main_path, sub_path):
    # 1. Load Files
    df_main = pd.read_excel(main_path)
    df_sub = pd.read_excel(sub_path)
    
    # 2. Clean Columns
    df_main = clean_cols(df_main)
    df_sub = clean_cols(df_sub)
    
    # 3. Canonicalize Keys (Strict String)
    if "MAHALLEKAYITNO" in df_main.columns:
        df_main["MAHALLEKAYITNO"] = df_main["MAHALLEKAYITNO"].apply(clean_id)
    if "MAHALLEKAYITNO" in df_sub.columns:
        df_sub["MAHALLEKAYITNO"] = df_sub["MAHALLEKAYITNO"].apply(clean_id)
        
    # 4. Merge
    # Outer join to keep all data
    df_full = df_main.merge(df_sub, on="MAHALLEKAYITNO", how="outer", suffixes=("", "_sub"))
    
    return df_full

@st.cache_data
def load_geo(path: str) -> gpd.GeoDataFrame:
    gdf = gpd.read_file(path)
    gdf = clean_cols(gdf)

    # ID kolonu: geojson'da MAHALLEKOD bekliyoruz (shp'de de genellikle var)
    if "MAHALLEKOD" in gdf.columns:
        # Strict String Canonicalization
        gdf["MAHALLEKOD"] = gdf["MAHALLEKOD"].apply(clean_id)

    # CRS
    try:
        if gdf.crs is None:
            gdf.set_crs(epsg=4326, inplace=True)
        elif gdf.crs.to_epsg() != 4326:
            gdf = gdf.to_crs(epsg=4326)
    except Exception:
        pass

    # Eğer dataset Adana+Mersin ise Adana’yı ayıkla (varsa il adı kolonu)
    # Kolon adı değişebileceği için olabildiğince esnek davran
    il_cols = [c for c in gdf.columns if normalize_text(c) in ["iladi", "il_adi", "il"]]
    if il_cols:
        ilc = il_cols[0]
        gdf = gdf[gdf[ilc].astype(str).str.upper().str.contains("ADANA", na=False)]

    return gdf

# -------------------- App --------------------
def check_password():
    """Returns `True` if the user had the correct password."""

    def password_entered():
        """Checks whether a password entered by the user is correct."""
        if st.session_state["password"] == st.secrets["general"]["password"]:
            st.session_state["password_correct"] = True
            del st.session_state["password"]  # don't store password
        else:
            st.session_state["password_correct"] = False

    if "password_correct" not in st.session_state:
        # First run, show input for password.
        st.text_input(
            "Password", type="password", on_change=password_entered, key="password"
        )
        return False
    elif not st.session_state["password_correct"]:
        # Password not correct, show input + error.
        st.text_input(
            "Password", type="password", on_change=password_entered, key="password"
        )
        st.error("😕 Password incorrect")
        return False
    else:
        # Password correct.
        return True

# -------------------- App --------------------
def main():
    st.set_page_config(page_title="Adana Mahalle Kırılganlık Paneli", layout="wide")
    
    if not check_password():
        st.stop()
        
    st.title("Adana Mahalle Kırılganlık Paneli")

    # Load Data (Centralized & Cached)
    # Ensure files exist (download if needed)
    xlsx_main_path = ensure_file(XLSX_MAIN, "main_excel")
    xlsx_sub_path = ensure_file(XLSX_SUB, "sub_excel")
    geo_path = ensure_file(GEO_PATH, "geo_file")

    df = load_data_central(xlsx_main_path, xlsx_sub_path)
    gdf = load_geo(geo_path)
    
    # Debug info for Tech tab
    raw_len = len(df)
    adana_len = len(df[df["İLADI"].astype(str).str.upper().str.contains("ADANA", na=False)]) if "İLADI" in df.columns else raw_len
    
    # Base Identity Columns
    ilce_col = "İLÇEADI" if "İLÇEADI" in df.columns else None
    name_col = "MAHALLEKÖYADI" if "MAHALLEKÖYADI" in df.columns else ("MAHALLEKOYADI" if "MAHALLEKOYADI" in df.columns else None)
    kent_col = "KENTKIRSINIFLAMASI" if "KENTKIRSINIFLAMASI" in df.columns else None
    
    # -------------------- Sidebar Flow (The Funnel) --------------------
    st.sidebar.header("Filtreler")
    
    # 1. District Selection (Stateful)
    if "selected_district" not in st.session_state:
        st.session_state.selected_district = "Tüm İlçeler"
        
    districts = ["Tüm İlçeler"] + sorted(df[ilce_col].dropna().astype(str).unique().tolist()) if ilce_col else []
    sel_dist = st.sidebar.selectbox("1. İlçe Seçimi", districts, key="selected_district")
    
    # Filter Data by District
    df_filtered = df.copy()
    if sel_dist != "Tüm İlçeler" and ilce_col:
        df_filtered = df_filtered[df_filtered[ilce_col] == sel_dist]
        
    # 2. Urbanity Selection
    if "selected_urbanity" not in st.session_state:
        st.session_state.selected_urbanity = "Tümü"
        
    urban_opts = ["Tümü"] + sorted(df_filtered[kent_col].dropna().astype(str).unique().tolist()) if kent_col else []
    sel_urban = st.sidebar.selectbox("2. KentsellikStatüsü", urban_opts, key="selected_urbanity")
    
    # Filter Data by Urbanity
    if sel_urban != "Tümü" and kent_col:
         df_filtered = df_filtered[df_filtered[kent_col] == sel_urban]

    # 3. Metric Group Selection
    # Build Metadata
    meta_map = build_metric_metadata(df)
    
    # Group names
    available_groups = sorted(list({m.group for m in meta_map.values()}))
    # Ensure logical order if possible
    priority = ["Ana Endeksler", "Alt Endeksler", "Kentsel Kırılganlık", "Kırsal Kırılganlık"]
    available_groups.sort(key=lambda x: priority.index(x) if x in priority else 99)
    
    if "selected_group" not in st.session_state:
        st.session_state.selected_group = available_groups[0] if available_groups else None
        
    sel_group = st.sidebar.radio("3. Metrik Grubu", available_groups, key="selected_group")
    
    # 4. Metric Selection
    group_metrics = [m for m in meta_map.values() if m.group == sel_group]
    metric_labels = [m.label for m in group_metrics]
    metric_label_map = {m.label: m.col_name for m in group_metrics}
    
    if "selected_metric_label" not in st.session_state:
         st.session_state.selected_metric_label = metric_labels[0] if metric_labels else None
         
    # Ensure selection is valid for current group
    if st.session_state.selected_metric_label not in metric_labels:
        st.session_state.selected_metric_label = metric_labels[0]
        
    sel_label = st.sidebar.selectbox("4. Metrik", metric_labels, key="selected_metric_label")
    selected_metric_col = metric_label_map[sel_label]
    selected_meta = meta_map[selected_metric_col]
    
    # -------------------- Metric Prep & Coverage --------------------
    # Calculate coverage BEFORE filtering by score (but AFTER district/urban filters)
    total_rows = len(df_filtered)
    valid_data_count = df_filtered[selected_metric_col].count()
    coverage_pct = (valid_data_count / total_rows * 100) if total_rows > 0 else 0
    
    st.sidebar.caption(f"Veri Kapsamı: %{coverage_pct:.1f} ({valid_data_count}/{total_rows} mahalle)")
    
    # Prepare Metric Data (Clean & Norm)
    # Note: We do this on the filtered dataframe
    raw_s, norm_s = prepare_metric_data(df_filtered, selected_meta)
    
    df_filtered["val_raw"] = raw_s
    df_filtered["score_norm"] = norm_s
    
    # 5. Smart Filters (Map Settings)
    with st.sidebar.expander("Gelişmiş Filtreler", expanded=True):
        # Auto-range slider (0-1 default, but customizable)
        use_norm_filter = st.checkbox("Normalize Skor (0-1) Kullan", value=True, help="Kapalıysa ham değerlere göre filtreler")
        
        if use_norm_filter:
            min_s, max_s = st.slider("Filtre Aralığı", 0.0, 1.0, (0.0, 1.0), 0.05)
            mask = (df_filtered["score_norm"] >= min_s) & (df_filtered["score_norm"] <= max_s)
        else:
            # Raw filter - find min/max first
            rmin = float(df_filtered["val_raw"].min())
            rmax = float(df_filtered["val_raw"].max())
            min_s, max_s = st.slider("Ham Değer Aralığı", rmin, rmax, (rmin, rmax))
            mask = (df_filtered["val_raw"] >= min_s) & (df_filtered["val_raw"] <= max_s)
            
        map_style_opts = {
            "Şeffaf (Beyaz Zeminde)": None,
            "Açık (Light)": "mapbox://styles/mapbox/light-v9", 
            "Koyu (Dark)": "mapbox://styles/mapbox/dark-v9",
            "Uydu": "mapbox://styles/mapbox/satellite-v9"
        }
        map_style_choice = st.sidebar.selectbox("Harita Altlığı", list(map_style_opts.keys()), index=0)
        selected_map_style = map_style_opts[map_style_choice]
        
    topn = st.sidebar.slider("Top N (Tablo Basamak Sayısı)", 10, 200, 30, 10)
    
    df_final = df_filtered[mask].copy()

    # -------------------- Final Merge --------------------
    # We now merge only the FINAL filtered dataset with GeoJSON
    # But we need basic columns for context
    
    # Ensure keys are ready
    # (Already canonicalized in load function)
    
    joined = gdf.merge(df_final, left_on="MAHALLEKOD", right_on="MAHALLEKAYITNO", how="left", suffixes=("_geo", ""))
    
    # 'has_data' logic
    joined["_has"] = ~joined["score_norm"].isna()
    # Filter for map display (only valid matches)
    joined_valid = joined[joined["_has"]].copy()

    if joined_valid.empty:
        st.warning("Seçili filtrelerde haritaya düşen mahalle bulunamadı (join sonucu boş).")
        st.stop()

    joined_valid["fill_color"] = colors_from_01(joined_valid["score_norm"].to_numpy()).tolist()

    # KPI
    c1, c2, c3 = st.columns(3)
    c1.metric("Mahalle sayısı (haritada)", f"{len(joined_valid):,}")
    c2.metric(f"{sel_label} ort.", f"{joined_valid['val_raw'].mean():.3f}")
    
    # --- TABS ---
    tab_map, tab_charts, tab_tables, tab_detail, tab_debug = st.tabs(["Harita", "İstatistikler", "Tablolar", "Mahalle Detay Analizi", "Teknik (Debug)"])

    with tab_map:
        # Map Settings
        # height = 750 (4:3 aspect ratio approx)
        layer = pdk.Layer(
            "GeoJsonLayer",
            joined_valid,
            pickable=True,
            stroked=True,
            filled=True,
            get_fill_color="fill_color",
            get_line_color=[0, 0, 0, 100],
            line_width_min_pixels=1,
            get_position=[35.3213, 37.0], # Dummy center, deckgl auto-centers usually
        )

        view_state = pdk.ViewState(
            latitude=37.0,
            longitude=35.3213,
            zoom=9,
            pitch=0,
        )

        tooltip = {
            "html": f"<b>Mahalle:</b> {{{name_col}}}<br/><b>İlçe:</b> {{{ilce_col}}}<br/><b>{sel_label}:</b> {{val_raw}}",
            "style": {"backgroundColor": "steelblue", "color": "white"}
        }

        # Layout: 3/4 Map, 1/4 Legend/Info (Implemented via columns)
        c_map, c_dummy = st.columns([3, 1])
        with c_map:
            st.pydeck_chart(pdk.Deck(
                map_style=selected_map_style,
                initial_view_state=view_state,
                layers=[layer],
                tooltip=tooltip
            ), use_container_width=True, height=750) 
        
        with c_dummy:
             # Legend (Simple HTML overlay simulation)
             st.markdown("#### Lejant")
             st.markdown(f"**{sel_label}**")
             st.markdown(
                 """
                 <div style='background: linear-gradient(to right, rgb(44,123,182), rgb(171,217,233), rgb(255,255,191), rgb(253,174,97), rgb(215,25,28)); height: 20px; width: 100%; border-radius: 5px;'></div>
                 <div style='display: flex; justify_content: space-between; font-size: 0.8em;'>
                     <span>Düşük</span>
                     <span>Yüksek</span>
                 </div>
                 """, unsafe_allow_html=True
             )
             st.info("Normalize edilmiş (0-1) skala kullanılır.")

    with tab_charts:
        # Histogram
        import plotly.express as px
        try:
            fig = px.histogram(
                joined_valid, 
                x="val_raw", 
                nbins=30, 
                title=f"{sel_label} Dağılımı",
                color_discrete_sequence=["#4a8bc2"],
                labels={"val_raw": sel_label}
            )
            fig.update_layout(bargap=0.1)
            st.plotly_chart(fig, use_container_width=True)
        except Exception as e:
            st.error(f"Grafik oluşturulamadı: {e}")

    with tab_tables:
        # Top N table
        st.subheader(f"Top {topn} mahalle (seçili skora göre)")
        show_cols = [c for c in [ilce_col, name_col, kent_col] if c and c in joined_valid.columns]
        # Ekle: Raw Value ve Normalized Column
        display_df = joined_valid.copy()
        # Drop original column if it exists to avoid rename collision
        if selected_metric_col in display_df.columns:
            display_df = display_df.drop(columns=[selected_metric_col])
            
        display_df = display_df.rename(columns={"val_raw": sel_label, "score_norm": f"{sel_label} (Norm)"})
        
        final_cols = show_cols + [sel_label, f"{sel_label} (Norm)"]
        
        top = display_df.sort_values(sel_label, ascending=False).head(topn)[final_cols]
        st.dataframe(top, use_container_width=True)

        # Download
        st.subheader("İndir")
        csv = display_df[final_cols].to_csv(index=False).encode("utf-8-sig")
        st.download_button("Filtrelenmiş tabloyu indir (CSV)", data=csv, file_name="adana_filtered.csv", mime="text/csv", key="download_filtered_csv")

    with tab_detail:
        # --- DETAIL VIEW (Mahalle Karnesi) ---
        st.header(f"Mahalle Detay Analizi")
        
        # Mahalle seçimi
        if name_col and name_col in joined_valid.columns:
            # 1. İlçe Seçimi (Filtreleme için)
            if ilce_col and ilce_col in joined_valid.columns:
                district_list = ["Tümü"] + sorted(joined_valid[ilce_col].astype(str).unique().tolist())
                selected_district_det = st.selectbox("İlçe Filtrele (Detay):", district_list)
                
                if selected_district_det != "Tümü":
                    det_filtered_df = joined_valid[joined_valid[ilce_col] == selected_district_det]
                else:
                    det_filtered_df = joined_valid
            else:
                det_filtered_df = joined_valid

            # 2. Mahalle Seçimi
            if ilce_col:
                det_filtered_df["_display_name"] = det_filtered_df[name_col].astype(str) + " (" + det_filtered_df[ilce_col].astype(str) + ")"
            else:
                det_filtered_df["_display_name"] = det_filtered_df[name_col].astype(str)
            
            mahalle_display_list = sorted(det_filtered_df["_display_name"].unique().tolist())
            selected_display_name = st.selectbox("İncelemek istediğiniz mahalleyi seçin:", mahalle_display_list)
            
            # Seçilen mahalle datası
            m_data = det_filtered_df[det_filtered_df["_display_name"] == selected_display_name].iloc[0]
            
            # Kart Görünümü
            k1, k2, k3 = st.columns(3)
            k1.metric("Mahalle", str(m_data[name_col]))
            k2.metric(f"{sel_label} (Ham)", f"{m_data['val_raw']:.3f}")
            k3.metric(f"Normalize Skor", f"{m_data['score_norm']:.3f}")
            
            st.divider()
            
            # Radar Grafik Yardımı
            def render_radar(group_name, title, color="#4a8bc2"):
                target_cols = [m.col_name for m in meta_map.values() if m.group == group_name]
                # we use 'df' (full dataset) for mn/mx/avg to have a global context
                valid_cols = [c for c in target_cols if c in df.columns]
                if not valid_cols:
                    return
                
                # Şehir Ortalaması (Full dataset)
                group_avg = df[valid_cols].mean()
                categories_short = [meta_map[c].label for c in valid_cols]
                
                # Normalize values for radar
                m_norm_vals = []
                avg_norm_vals = []
                for c in valid_cols:
                    series = df[c].astype(float) # global series
                    mn, mx = series.min(), series.max()
                    val = float(m_data[c]) if pd.notna(m_data[c]) else 0.0
                    avg = float(group_avg[c])
                    if mx > mn:
                        m_norm_vals.append((val-mn)/(mx-mn))
                        avg_norm_vals.append((avg-mn)/(mx-mn))
                    else:
                        m_norm_vals.append(0)
                        avg_norm_vals.append(0)

                fig = go.Figure()
                fig.add_trace(go.Scatterpolar(r=m_norm_vals, theta=categories_short, fill='toself', name=str(m_data[name_col]), line_color=color))
                fig.add_trace(go.Scatterpolar(r=avg_norm_vals, theta=categories_short, fill='toself', name='Şehir Ortalaması', line_color="gray"))
                
                fig.update_layout(
                    polar=dict(radialaxis=dict(visible=True, range=[0, 1])),
                    showlegend=True,
                    title=title,
                    height=400,
                    margin=dict(l=40, r=40, t=40, b=40)
                )
                # Unique key prevents stale visuals
                st.plotly_chart(fig, use_container_width=True, key=f"radar_{group_name}_{m_data.name}")

            def render_bar(group_name, title, color="#ff4b4b"):
                target_cols = [m.col_name for m in meta_map.values() if m.group == group_name]
                valid_cols = [c for c in target_cols if c in df.columns]
                if not valid_cols:
                    return
                
                labels = [meta_map[c].label for c in valid_cols]
                m_vals = [m_data[c] if pd.notna(m_data[c]) else 0.0 for c in valid_cols]
                c_avgs = [df[c].mean() for c in valid_cols]
                
                fig = go.Figure()
                # Mahalle
                fig.add_trace(go.Bar(
                    y=labels, x=m_vals, name=str(m_data[name_col]),
                    orientation='h', marker_color=color
                ))
                # Ortalama
                fig.add_trace(go.Bar(
                    y=labels, x=c_avgs, name='Şehir Ortalaması',
                    orientation='h', marker_color='#dddddd'
                ))
                
                fig.update_layout(
                    barmode='group',
                    title=title,
                    height=400,
                    margin=dict(l=150, r=20, t=50, b=50),
                    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
                )
                st.plotly_chart(fig, use_container_width=True, key=f"bar_{group_name}_{m_data.name}")

            # --- Görselleştirme ---
            c_det1, c_det2 = st.columns(2)
            with c_det1:
                render_bar("Ana Endeksler", "Ana Endeks Karşılaştırması", color="#ff4b4b")
            with c_det2:
                render_radar("Alt Endeksler", "Alt Endeks Karşılaştırması", color="#4a8bc2")
            
            # --- Tablo Görünümü ---
            st.subheader("Tüm Endeks Değerleri")
            all_target_cols = [m.col_name for m in meta_map.values() if m.group in ["Ana Endeksler", "Alt Endeksler"]]
            valid_all = [c for c in all_target_cols if c in df.columns]
            
            if valid_all:
                res_df = pd.DataFrame({
                    "Endeks": [meta_map[c].label for c in valid_all],
                    "Grup": [meta_map[c].group for c in valid_all],
                    "Mahalle (Ham)": [m_data[c] for c in valid_all],
                    "Şehir Ort.": [df[c].mean() for c in valid_all]
                })
                st.dataframe(res_df.style.format({"Mahalle (Ham)": "{:.3f}", "Şehir Ort.": "{:.3f}"}), use_container_width=True)


    with tab_debug:
        st.write(f"**Excel Raw (Load)**: {raw_len}")
        st.write(f"**Excel Adana Filtered**: {adana_len}")
        if raw_len > adana_len:
             st.warning(f"Adana filtresi {raw_len - adana_len} satırı eledi. (İLADI != ADANA veya NaN)")

        st.write(f"**Excel Toplam Satır (Final)**: {len(df)}")
        st.write(f"**GeoJSON Toplam Satır**: {len(gdf)}")
        st.write(f"**Harita Join (Geo+Excel)**: {len(joined)}")
        st.write(f"**Geçerli Veri (NaN olmayan)**: {len(joined_valid)}")
        st.write(f"**NaN Olanlar**: {joined['score_norm'].isna().sum()}")
        
        st.divider()
        st.write("### MERGE DEBUG")
        st.write("GeoJSON Key (MAHALLEKOD) dtype:", gdf["MAHALLEKOD"].dtype)
        st.write("Excel Key (MAHALLEKAYITNO) dtype:", df["MAHALLEKAYITNO"].dtype)
        
        st.write("GeoJSON Sample:", gdf["MAHALLEKOD"].head(3).tolist())
        st.write("Excel Sample:", df["MAHALLEKAYITNO"].head(3).tolist())
        
        # Check intersection
        geo_keys = set(gdf["MAHALLEKOD"].dropna())
        excel_keys = set(df["MAHALLEKAYITNO"].dropna())
        intersection = geo_keys.intersection(excel_keys)
        st.write(f"**Ortak ID Sayısı**: {len(intersection)}")
        st.write(f"**Excel'de olup Haritada Olmayan**: {len(excel_keys - geo_keys)}")
        st.write(f"**Haritada olup Excel'de Olmayan**: {len(geo_keys - excel_keys)}")

        st.divider()
        st.write(f"### '{sel_label}' Analizi")
        st.write(f"**Kolon Tipi**: {df[selected_metric_col].dtype}")
        st.write(f"**Örnek Veriler (İlk 5)**: {df[selected_metric_col].head(5).tolist()}")
        st.write(f"**Raw Excel (Merged Sheets)** Satır Sayısı: {len(df)}")
        st.write(f"**Raw Excel '{sel_label}' Dolu Veri**: {df[selected_metric_col].count()}")
        st.write(f"**Raw Excel '{sel_label}' NaN Sayısı**: {df[selected_metric_col].isna().sum()}")
        st.write(f"**Final Joined '{sel_label}' Dolu Veri**: {joined['score_norm'].count()}")
        
        if df[selected_metric_col].isna().sum() > 0:
            st.warning(f"Dikkat: Excel verisinde '{sel_label}' kolonu için {df[selected_metric_col].isna().sum()} adet boş (NaN) satır var. Merge öncesi veride eksiklik olabilir.")

if __name__ == "__main__":
    main()
