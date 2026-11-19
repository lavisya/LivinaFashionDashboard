import io
import os
import sqlite3

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

st.set_page_config(page_title="Livina Fashion Dashboard", layout="wide")

# declare variabel yg akan dipake constantly (sama spt const javascript)
DB = "livinaFashion.db"  # [UBAH 1] dulu "livina_fashion.db", disamakan dengan nama database hasil load
YEARS = [2023, 2024, 2025]
BASELINE = "2023-07"  # transaksi pertama yang bisa dikategorikan produk baru
TAHAP = ["Growth", "Maturity", "Introduction", "Decline"]
WARNA = {
    "Growth": "#2a78d6",
    "Maturity": "#1baf7a",
    "Introduction": "#eda100",
    "Decline": "#e34948",
}
WARNA_TEKS = {"Growth": "blue", "Maturity": "green", "Introduction": "orange", "Decline": "red"}
INK = "#2B2B2B"

# untk tampilan UI
st.markdown(
    """
    <style>
    .stApp { background: #F7EFEA; }
    header[data-testid="stHeader"] { background: transparent; }
    .block-container {
        padding-top: 2rem;
        padding-left: 1.5rem;
        padding-right: 1.5rem;
        max-width: 100%;
    }

    /* kartu di baris atas */
    .kpi {
        background: #FFC9D4;
        border-radius: 18px;
        padding: 12px 8px;
        min-height: 200px; /* [UBAH 4] dulu 150px, dinaikkan supaya baris target, nilai tahun lalu, dan status muat */
        text-align: center;
        color: #2B2B2B;
    }
    .kpi-title { font-size: 15px; line-height: 1.25; }
    .kpi-value { font-size: 22px; font-weight: 600; margin: 6px 0 4px; white-space: nowrap; }
    .kpi-sub { font-size: 12px; line-height: 1.4; }
    .muted { color: #7A6A70; }
    .ok { color: #1f7a4d; font-weight: 600; }
    .bad { color: #c0392b; font-weight: 600; }

    /* panel konten */
    [class*="st-key-panel_"] {
        background: #FDE0E8;
        border: none !important;
        border-radius: 22px;
        padding: 16px 22px;
    }
    .panel-title { font-size: 20px; color: #2B2B2B; margin-bottom: 4px; }
    .panel-note { font-size: 13px; color: #7A6A70; margin-bottom: 4px; }

    /* year, search */
    div[data-baseweb="select"] > div,
    div[data-baseweb="input"] {
        background: #FFF5F8;
        border: none;
        border-radius: 14px;
    }
    /* ilangin toolbar di panel */
    .modebar, .modebar-container { display: none !important; } 
    /* ilangin toolbar di tabel (new products) */
    [data-testid="stElementToolbar"] { display: none !important; }

    .stButton > button, .stDownloadButton > button {
        background: #E0AECB;
        color: #2B2B2B;
        border: none;
        border-radius: 14px;
        width: 100%;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# open session ke database
@st.cache_data
def run_query(sql, params=()):
    con = sqlite3.connect(DB)
    try:
        return pd.read_sql_query(sql, con, params=params) # sql = preparestatement, con = connection, params = value nya spt set integer (1, year)
    finally:
        con.close()

@st.cache_data
def load_base():
    waktu = run_query("SELECT * FROM Dim_Waktu ORDER BY Bulan_Key")
    produk = run_query("SELECT * FROM Dim_Produk ORDER BY Produk_Key")

    # R(p,t): revenue bulanan tiap produk (dijumlah dari semua pelanggan)
    bulanan = run_query(
        """
        SELECT Produk_Key, Bulan_Key, SUM(Revenue) AS Revenue
        FROM Fact_Sales
        GROUP BY Produk_Key, Bulan_Key
        """
    )
    # bulan transaksi pertama tiap produk
    pertama = run_query(
        """
        SELECT Produk_Key, MIN(Bulan_Key) AS Bulan_Pertama
        FROM Fact_Sales
        WHERE Revenue > 0
        GROUP BY Produk_Key
        """
    )
    # [UBAH 2] persentase pertumbuhan per produk per bulan, sekarang langsung dari Fact_PLC (sudah satu baris per produk per bulan, jadi tidak perlu MAX lagi)
    # dulu: SELECT ..., MAX(Persentase_Pertumbuhan) AS Pertumbuhan FROM Fact_Sales GROUP BY Produk_Key, Bulan_Key
    pertumbuhan = run_query(
        """
        SELECT Produk_Key, Bulan_Key, Persentase_Pertumbuhan AS Pertumbuhan
        FROM Fact_PLC
        """
    )

    bulan_list = waktu["Bulan_Key"].tolist()
    rev = (
        bulanan.pivot_table(index="Produk_Key", columns="Bulan_Key", values="Revenue", aggfunc="sum") # jadiin tabel, produk jadi row, bulan jadi kolom dan isinya revenue
        .reindex(index=produk["Produk_Key"], columns=bulan_list) # cocokin setiap produk dengan bulan yg ada di list
        .fillna(0) # isi kolom yg kosong dengan 0
    )
    # [BARU] tabel pertumbuhan, bentuknya sama seperti rev. TIDAK di-fillna(0), karena kosong berarti "tidak bisa dihitung"
    # [UBAH 2] pivot_table(..., aggfunc="max") diganti pivot(...), karena Fact_PLC sudah unik per (Produk_Key, Bulan_Key)
    growth = (
        pertumbuhan.pivot(index="Produk_Key", columns="Bulan_Key", values="Pertumbuhan")
        .reindex(index=produk["Produk_Key"], columns=bulan_list)
    )
    first_month = pertama.set_index("Produk_Key")["Bulan_Pertama"].reindex(rev.index) # setting bulan pertama
    return waktu, produk, bulan_list, rev, growth, first_month 

waktu_df, produk_df, bulan_list, rev, growth, first_month = load_base() # declare diluar function untk bisa dipakai terus

# KLASIFIKASI TAHAP PRODUK (aturan R1 - R5), pada akhir tahun
@st.cache_data
def classify(year):
    akhir = bulan_list.index(f"{year}-12") # akhir tahun
    hasil = []

    for produk, baris in rev.iterrows():
        fm = first_month[produk]
        if pd.isna(fm) or fm > f"{year}-12":  # produk belum ada di tahun itu
            continue

        v = baris.values
        usia_produk = akhir - bulan_list.index(fm) + 1 # bulan akhir - bulan pertama kali muncul (+1 untk digitung as 1)
        g_rata = np.nan # not a number jadi default value kalau ga ada

        # operator : untk include sebelum :, dan exlude setelah :
        # untk ambil 3 bulan terakhir
        # == 0 adalah untk compare dari 3 bulan itu, balikan boolean
        # .all semua harus 0 untk menyatakan dia true
        if (v[akhir - 2: akhir + 1] == 0).all():  # R1
            tahap, alasan = "Decline", "Berhenti terjual"
        elif fm >= BASELINE and usia_produk <= 12:  # R2
            tahap, alasan = "Introduction", "Produk baru"
        # ambil growth 3 bulan terakhir 
        else:  # R3 - R5
            g = growth.loc[produk].values[akhir - 2: akhir + 1]
            g = g[~np.isnan(g)]  # buang bulan yang kosong (pembagi 0 / belum cukup data)

            # [UBAH 3] dulu: g_rata = np.mean(g) if len(g) else np.inf  (hasil klasifikasi sama, hanya dibuat eksplisit tanpa trik inf)
            if len(g) == 0:
                # semua pertumbuhan tidak bisa dihitung (MA bulan sebelumnya 0): produk terjual lagi setelah lama tidak terjual
                # keputusan sementara: dianggap Growth. Ganti ke "Maturity" kalau kamu memilih itu
                g_rata = np.nan
                tahap, alasan = "Growth", "Penjualan naik"
            else:
                g_rata = np.mean(g)

                if g_rata > 10:
                    tahap, alasan = "Growth", "Penjualan naik"
                elif g_rata < -10:
                    tahap, alasan = "Decline", "Penjualan menurun"
                else:
                    tahap, alasan = "Maturity", "Penjualan stabil"

        hasil.append((produk, tahap, alasan, g_rata))

    return pd.DataFrame(hasil, columns=["Produk_Key", "Tahap", "Alasan", "G_rata"])

# PERHITUNGAN KPI
def kpi_tahap(year):
    df = classify(year) # declare data frame nya
    n_intro = int((df["Tahap"] == "Introduction").sum())
    penyebut = len(df) - n_intro
    n_growth = int((df["Tahap"] == "Growth").sum())
    n_decline = int((df["Tahap"] == "Decline").sum())
    return {
        "Introduction": n_intro,
        "Growth": n_growth,
        "Maturity": int((df["Tahap"] == "Maturity").sum()),
        "Decline": n_decline,
        "berhenti": int((df["Alasan"] == "Berhenti terjual").sum()),
        "menurun": int((df["Alasan"] == "Penjualan menurun").sum()),
        "pct_growth": n_growth / penyebut * 100 if penyebut else np.nan,
        "pct_decline": n_decline / penyebut * 100 if penyebut else np.nan,
    }


def success_rate(year):
    """produk baru tahun sebelumnya yang Growth/Maturity di akhir tahun terpilih.
    return (berhasil, total) atau None kalau tahun dasar"""
    if year == YEARS[0]:
        return None
    prev = year - 1
    lo = max(f"{prev}-01", BASELINE)
    kohort = first_month[(first_month >= lo) & (first_month <= f"{prev}-12")].index
    tahap_now = classify(year).set_index("Produk_Key")["Tahap"].reindex(kohort)
    return int(tahap_now.isin(["Growth", "Maturity"]).sum()), len(kohort)


def stage_revenue(year):
    """% revenue setahun per tahap (tahap = tahap produk di akhir tahun itu)"""
    cols = [m for m in bulan_list if m.startswith(str(year))]
    rev_year = rev[cols].sum(axis=1)
    tahap = classify(year).set_index("Produk_Key")["Tahap"]
    per_tahap = rev_year.reindex(tahap.index).groupby(tahap).sum()
    total = rev_year.sum()
    return {t: per_tahap.get(t, 0) / total * 100 for t in TAHAP}


def new_products(year):
    """produk yang transaksi pertamanya di tahun terpilih (bukan produk baseline)"""
    lo = max(f"{year}-01", BASELINE)
    baru = first_month[(first_month >= lo) & (first_month <= f"{year}-12")].sort_values()
    tabel = produk_df.set_index("Produk_Key").loc[baru.index, ["Nama_Produk", "Kategori"]].copy()
    return tabel.rename(columns={"Nama_Produk": "Produk"}).reset_index(drop=True)


# =====================================================================
# FORMAT TAMPILAN
# =====================================================================
def persen(x, desimal=1):
    return f"{x:.{desimal}f}".replace(".", ",") + "%"


def rupiah_singkat(x):
    """2145962900 -> 'Rp 2,15 M' (M = miliar)"""
    return "Rp " + f"{x / 1_000_000_000:.2f}".replace(".", ",") + " M"


def panah(delta):
    arah = "▲" if delta > 0 else ("▼" if delta < 0 else "=")
    return f"{arah} {abs(delta):.1f}".replace(".", ",") + " poin"


def kpi_card(title, value="-", subs=None):
    """kartu kecil di baris atas. subs = [(teks, kelas_css), ...]"""
    baris = "".join(f'<div class="kpi-sub {css}">{teks}</div>' for teks, css in (subs or []))
    return (
        f'<div class="kpi">'
        f'<div class="kpi-title">{title}</div>'
        f'<div class="kpi-value">{value}</div>'
        f"{baris}"
        f"</div>"
    )


def baris_kpi(nilai, nilai_lalu, lebih_tinggi_lebih_baik, tahun_lalu):
    """satu baris kecil di kartu: bandingkan dengan tahun sebelumnya"""
    if nilai_lalu is None:
        return [("Tahun dasar", "muted")]
    delta = nilai - nilai_lalu
    if round(delta, 1) == 0:
        return [(f"Sama dengan {tahun_lalu}", "muted")]
    teks = "Lebih banyak" if delta > 0 else "Lebih sedikit"
    baik = (delta > 0) == lebih_tinggi_lebih_baik
    return [(f"{teks} dari {tahun_lalu}", "ok" if baik else "bad")]


def subs_kpi(nilai, nilai_lalu, tahun_lalu, target_teks, tercapai):
    """[UBAH 4] baris kecil kartu KPI: persentase, nilai tahun lalu, target, dan status.
    tercapai = fungsi (nilai, nilai_lalu) -> True/False, dibandingkan setelah dibulatkan 1 desimal (sama dengan yang tampil)"""
    ada = nilai_lalu is not None and not (np.isnan(nilai) or np.isnan(nilai_lalu))
    label = f"{tahun_lalu}" if nilai_lalu is not None else "Tahun lalu"
    baris = [
        ("Persentase: " + (persen(nilai) if not np.isnan(nilai) else "-"), ""),
        (f"{label}: " + (persen(nilai_lalu) if ada else "-"), "muted"),
        (f"Target: {target_teks}", "muted"),
    ]
    if not ada:
        baris.append(("Tahun dasar", "muted"))
    elif tercapai(round(nilai, 1), round(nilai_lalu, 1)):
        baris.append(("✔ Tercapai", "ok"))
    else:
        baris.append(("✘ Belum tercapai", "bad"))
    return baris


def panel(title, key, height=340):
    """kotak panel. isi ditambah setelahnya dengan: with box: ..."""
    try:
        box = st.container(border=True, key=f"panel_{key}", height=height)
    except TypeError:  # streamlit lama belum punya key: jalan tapi tanpa warna pink
        box = st.container(border=True, height=height)
    with box:
        st.markdown(f'<div class="panel-title">{title}</div>', unsafe_allow_html=True)
    return box


def rapikan(fig, tinggi):
    fig.update_layout(
        height=tinggi,
        margin=dict(l=0, r=0, t=8, b=0),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color=INK),
    )
    return fig


# =====================================================================
# BARIS 1: logo + 6 kartu
# =====================================================================
logo_col, *card_cols = st.columns([2.4, 1, 1, 1, 1, 1, 1])

with logo_col:
    os.path.exists("logo.png")
    st.image("logo.png", width=320)

kartu = ["Total Revenue", "Introduction", "Growth", "Maturity", "Decline", "Success Rate"]
kpi_slots = {}
for col, nama in zip(card_cols, kartu):
    with col:
        kpi_slots[nama] = st.empty()
        kpi_slots[nama].markdown(kpi_card(nama), unsafe_allow_html=True)

# =====================================================================
# BARIS 2: year dan search (rata kanan)
# =====================================================================
st.write("")
_, year_col, search_col = st.columns([5.2, 1.4, 1.9])

# dropdown pilih tahun
with year_col:
    year = st.selectbox("Year", YEARS, index=len(YEARS) - 1, label_visibility="collapsed")

# search produk
with search_col:
    semua = run_query(
        """
        SELECT Produk_Key, Nama_Produk, Kategori
        FROM Dim_Produk
        ORDER BY Nama_Produk
        """
    )
    nama_dari_key = semua.set_index("Produk_Key")["Nama_Produk"]
    pilihan = st.selectbox(
        "Search",
        semua["Produk_Key"],
        index=None,
        format_func=lambda k: nama_dari_key[k],
        placeholder="Search product",
        label_visibility="collapsed",
    )
    selected_product = None
    if pilihan is not None:
        selected_product = semua[semua["Produk_Key"] == pilihan].iloc[0].to_dict()

# =====================================================================
# ISI KARTU
# =====================================================================
total_revenue = run_query(
    """
    SELECT COALESCE(SUM(f.Revenue), 0) AS Total
    FROM Fact_Sales f
    JOIN Dim_Waktu w ON f.Bulan_Key = w.Bulan_Key
    WHERE w.Tahun = ?
    """,
    (year,),
)["Total"][0]

kpi_slots["Total Revenue"].markdown(
    kpi_card("Total Revenue", rupiah_singkat(total_revenue)), unsafe_allow_html=True
)

sekarang = kpi_tahap(year)
lalu = kpi_tahap(year - 1) if year > YEARS[0] else None

kpi_slots["Introduction"].markdown(
    kpi_card("Introduction", sekarang["Introduction"]), unsafe_allow_html=True
)
kpi_slots["Growth"].markdown(
    kpi_card(
        "Growth",
        sekarang["Growth"],
        # [UBAH 4] dulu: baris_kpi(sekarang["pct_growth"], lalu["pct_growth"] if lalu else None, True, year - 1)
        subs_kpi(sekarang["pct_growth"], lalu["pct_growth"] if lalu else None, year - 1,
                 "lebih tinggi dari tahun lalu", lambda n, l: n > l),
    ),
    unsafe_allow_html=True,
)
kpi_slots["Maturity"].markdown(
    kpi_card("Maturity", sekarang["Maturity"]), unsafe_allow_html=True
)
kpi_slots["Decline"].markdown(
    kpi_card(
        "Decline",
        sekarang["Decline"],
        # [UBAH 4] dulu: baris_kpi(sekarang["pct_decline"], lalu["pct_decline"] if lalu else None, False, year - 1)
        subs_kpi(sekarang["pct_decline"], lalu["pct_decline"] if lalu else None, year - 1,
                 "lebih rendah dari tahun lalu", lambda n, l: n < l),
    ),
    unsafe_allow_html=True,
)

hasil_sr = success_rate(year)

# [UBAH 4] nilai Success Rate tahun lalu + target, dipakai di semua kondisi kartu Success Rate
sr_lalu = None
if year - 1 > YEARS[0]:  # success_rate(2023) tidak ada (tahun dasar), jadi tahun lalu baru ada untuk 2025
    hs = success_rate(year - 1)
    if hs and hs[1]:
        sr_lalu = hs[0] / hs[1] * 100
label_sr_lalu = f"{year - 1}" if year > YEARS[0] else "Tahun lalu"
subs_sr_info = [
    (f"{label_sr_lalu}: " + (persen(sr_lalu) if sr_lalu is not None else "-"), "muted"),
    ("Target: minimal 50%", "muted"),
]

if hasil_sr is None:
    kpi_slots["Success Rate"].markdown(
        kpi_card("Success Rate", "-", [("Tahun dasar", "muted")] + subs_sr_info + [("Belum bisa dinilai", "muted")]),
        unsafe_allow_html=True,
    )
else:
    berhasil, total_baru = hasil_sr
    if total_baru == 0:
        kpi_slots["Success Rate"].markdown(
            kpi_card("Success Rate", "-", [(f"Tidak ada produk baru {year - 1}", "muted")] + subs_sr_info + [("Belum bisa dinilai", "muted")]),
            unsafe_allow_html=True,
        )
    else:
        nilai_sr = berhasil / total_baru * 100
        css = "ok" if nilai_sr >= 50 else "bad"
        status_sr = ("✔ Tercapai", "ok") if round(nilai_sr, 1) >= 50 else ("✘ Belum tercapai", "bad")
        kpi_slots["Success Rate"].markdown(
            kpi_card(
                "Success Rate",
                persen(nilai_sr),
                [
                    (f"{berhasil} dari {total_baru} produk baru pada tahun {year - 1} dengan penjualan baik", css),
                ] + subs_sr_info + [status_sr],
            ),
            unsafe_allow_html=True,
        )

st.write("")
st.write("")

# =====================================================================
# BARIS 3: Monthly Revenue | New Products List | Customer Demography
# =====================================================================
c1, c2, c3 = st.columns(3, gap="large")

# ---------- Monthly Revenue ----------
with c1:
    box = panel(f"Monthly Revenue ({year})", "monthly")
    with box:
        if selected_product:
            bulanan = run_query(
                """
                SELECT w.Bulan_Key, SUM(f.Revenue) AS Revenue
                FROM Fact_Sales f
                JOIN Dim_Waktu w ON f.Bulan_Key = w.Bulan_Key
                WHERE f.Produk_Key = ?
                GROUP BY w.Bulan_Key
                """,
                (selected_product["Produk_Key"],),
            )
            st.markdown(
                f'<div class="panel-note">{selected_product["Nama_Produk"]} · '
                f'{selected_product["Kategori"]}</div>',
                unsafe_allow_html=True,
            )
        else:
            bulanan = run_query(
                """
                SELECT w.Bulan_Key, SUM(f.Revenue) AS Revenue
                FROM Fact_Sales f
                JOIN Dim_Waktu w ON f.Bulan_Key = w.Bulan_Key
                GROUP BY w.Bulan_Key
                """
            )
            st.markdown('<div class="panel-note">Seluruh produk</div>', unsafe_allow_html=True)

        bulan_tahun = [b for b in bulan_list if b.startswith(str(year))]
        seri = bulanan.set_index("Bulan_Key")["Revenue"].reindex(bulan_tahun).fillna(0)
        data_line = pd.DataFrame(
            {"Bulan": pd.to_datetime([b + "-01" for b in bulan_tahun]), "Revenue (juta)": seri.values / 1e6}
        )
        data_line["Revenue_fmt"] = ["Rp " + f"{v:,.0f}".replace(",", ".") for v in seri.values]
        fig = px.line(data_line, x="Bulan", y="Revenue (juta)", markers=True,
                      custom_data=["Revenue_fmt"])
        fig.update_traces(
            line_color="#D6336C", marker_color="#D6336C",
            hovertemplate="%{x|%b %Y}<br>Revenue: %{customdata[0]}<extra></extra>",
            hoverlabel=dict(bgcolor="white", font_color="#2B2B2B"),
        )
        fig.update_xaxes(
            tickmode="array",
            tickvals=[f"{year}-{m:02d}-01" for m in range(1, 13)],
            ticktext=["Jan", "Feb", "Mar", "Apr", "Mei", "Jun",
                      "Jul", "Agu", "Sep", "Okt", "Nov", "Des"],
            tickangle=0,
            title_text="",
        )
        st.plotly_chart(rapikan(fig, 230))

# ---------- New Products List ----------
with c2:
    box = panel("New Products List", "newproducts")
    with box:
        tabel_baru = new_products(year)
        st.markdown(
            f'<div class="panel-note">{len(tabel_baru)} produk baru pada {year}</div>',
            unsafe_allow_html=True,
        )
        if tabel_baru.empty:
            st.caption("Tidak ada produk baru pada tahun ini")
        else:
            st.dataframe(tabel_baru, hide_index=True, height=230)

# ---------- Customer Demography ----------
with c3:
    box = panel("Customer Demography", "demography")
    with box:
        pelanggan = run_query(
            """
            SELECT DISTINCT c.Customer_Key, c.Jenis_Kelamin, c.Kota, c.Umur
            FROM Fact_Sales f
            JOIN Dim_Waktu w ON f.Bulan_Key = w.Bulan_Key
            JOIN Dim_Customer c ON f.Customer_Key = c.Customer_Key
            WHERE w.Tahun = ?
            """,
            (year,),
        )
        valid = pelanggan[
            (pelanggan["Jenis_Kelamin"] != "Unknown") & (pelanggan["Kota"] != "Unknown")
        ]
        st.markdown(
            f'<div class="panel-note">{len(valid):,} pelanggan pada {year}</div>'.replace(",", "."),
            unsafe_allow_html=True,
        )
        tab_gender, tab_umur, tab_kota = st.tabs(["Jenis Kelamin", "Umur", "Kota"])

        with tab_gender:
            g = pelanggan["Jenis_Kelamin"]
            g = g[g != "Unknown"]
            gender = g.value_counts().reset_index()
            gender.columns = ["Jenis Kelamin", "Jumlah"]
            fig = px.pie(gender, names="Jenis Kelamin", values="Jumlah", hole=0.5,
                         color_discrete_sequence=["#D6336C", "#7B93DB", "#C9B7BE"])
            st.plotly_chart(rapikan(fig, 200))

        with tab_umur:
            umur = pelanggan["Umur"].dropna()
            kelompok = pd.cut(
                umur, bins=[0, 19, 24, 29, 34, 39, 49, 120],
                labels=["<20", "20-24", "25-29", "30-34", "35-39", "40-49", "50+"],
            ).value_counts().sort_index().reset_index()
            kelompok.columns = ["Kelompok Umur", "Jumlah"]
            fig = px.bar(kelompok, x="Kelompok Umur", y="Jumlah", color_discrete_sequence=["#D6336C"])
            st.plotly_chart(rapikan(fig, 200))

        with tab_kota:
            k = pelanggan["Kota"]
            k = k[k != "Unknown"]
            kota = k.value_counts().head(7).reset_index()
            kota.columns = ["Kota", "Jumlah"]
            fig = px.bar(kota.iloc[::-1], x="Jumlah", y="Kota", orientation="h",
                         color_discrete_sequence=["#D6336C"])
            st.plotly_chart(rapikan(fig, 200))

st.write("")

# =====================================================================
# BARIS 4: Revenue Stage | Recommendation | Product Ranking
# =====================================================================
c4, c5, c6 = st.columns(3, gap="large")

# ---------- Revenue Stage ----------
with c4:
    box = panel("Revenue Stage", "stage")
    with box:
        persen_tahap = {y: stage_revenue(y) for y in YEARS}
        st.markdown(
            '<div class="panel-note">Kontribusi setiap tahap terhadap penjualan</div>',
            unsafe_allow_html=True,
        )

        fig = go.Figure()
        for t in TAHAP:
            nilai = [persen_tahap[y][t] for y in YEARS]
            fig.add_bar(
                name=t, x=[str(y) for y in YEARS], y=nilai,
                marker_color=WARNA[t],
                marker_opacity=[1 if y == year else 0.45 for y in YEARS],
                text=[persen(v) if v >= 4 else "" for v in nilai],
                textposition="inside", textfont=dict(color="white", size=11),
                hovertemplate="%{x} · " + t + ": %{y:.1f}%<extra></extra>",
            )
        fig.update_layout(barmode="stack", legend=dict(orientation="h", y=-0.15, font=dict(size=10)))
        fig.update_yaxes(range=[0, 100], ticksuffix="%")
        st.plotly_chart(rapikan(fig, 220))

# ---------- Recommendation ----------
REKOMENDASI = {
    "Introduction": "Produk masih baru. Fokus pada pengenalan: tampilkan di toko dan tawarkan lewat WhatsApp, "
                    "pantau penjualan tiap bulan, dan jaga stok tetap secukupnya.",
    "Growth": "Penjualan naik. Pastikan stok selalu cukup, pertimbangkan menambah variasi, "
              "dan jadikan prioritas dalam promosi.",
    "Maturity": "Penjualan stabil. Pertahankan stok dan harga, jadikan produk andalan, "
                "dan padukan dengan produk lain agar penjualan tetap terjaga.",
    "Menurun": "Penjualan menurun. Evaluasi harga dan tampilan produk, pertimbangkan diskon atau paket "
               "bersama produk lain, dan kurangi pembelian stok baru.",
    "Berhenti": "Tidak ada transaksi pada tiga bulan terakhir. Cek sisa stok, pertimbangkan cuci gudang, "
                "atau putuskan apakah produk dihentikan.",
}
ARAH = {
    "Introduction": "Baru terjual",
    "Growth": "Meningkat",
    "Maturity": "Stabil",
    "Menurun": "Menurun",
    "Berhenti": "Berhenti terjual",
}

with c5:
    box = panel("Recommendation", "reco")
    with box:
        if not selected_product:
            st.markdown(
                '<div class="panel-note">Cari produk di kolom Search untuk melihat tahap '
                "dan rekomendasinya pada tahun yang dipilih.</div>",
                unsafe_allow_html=True,
            )
        else:
            klas = classify(year)
            baris = klas[klas["Produk_Key"] == selected_product["Produk_Key"]]
            st.markdown(f"**{selected_product['Nama_Produk']}** · {selected_product['Kategori']}")
            if baris.empty:
                st.markdown(f"Produk ini belum memiliki transaksi hingga akhir {year}.")
            else:
                r = baris.iloc[0]
                kunci = r["Tahap"]
                if r["Tahap"] == "Decline":
                    kunci = "Berhenti" if r["Alasan"] == "Berhenti terjual" else "Menurun"
                warna_teks = WARNA_TEKS[r["Tahap"]]
                st.markdown(f"Tahap pada akhir {year}: **:{warna_teks}[{r['Tahap']}]**")
                st.markdown(f"Arah penjualan: **{ARAH[kunci]}**")
                st.markdown(REKOMENDASI[kunci])

# ---------- Product Ranking ----------
with c6:
    box = panel("Product Ranking", "ranking")
    with box:
        top = run_query(
            """
            SELECT p.Produk_Key, p.Nama_Produk, p.Kategori, SUM(f.Quantity) AS Quantity
            FROM Fact_Sales f
            JOIN Dim_Waktu w ON f.Bulan_Key = w.Bulan_Key
            JOIN Dim_Produk p ON f.Produk_Key = p.Produk_Key
            WHERE w.Tahun = ?
            GROUP BY p.Produk_Key, p.Nama_Produk, p.Kategori
            ORDER BY Quantity DESC
            LIMIT 10
            """,
            (year,),
        )
        tahap_produk = classify(year).set_index("Produk_Key")["Tahap"]
        top["Tahap"] = top["Produk_Key"].map(tahap_produk)
        st.markdown(
            f'<div class="panel-note">10 produk dengan penjualan tertinggi pada tahun {year}</div>',
            unsafe_allow_html=True,
        )
        fig = px.bar(
            top.iloc[::-1], x="Quantity", y="Nama_Produk", orientation="h",
            color="Tahap", color_discrete_map=WARNA,
            hover_data={"Kategori": True, "Produk_Key": False},
            labels={"Nama_Produk": ""},
        )
        fig = rapikan(fig, 250)
        fig.update_xaxes(title_text="")  # hapus judul di tengah
        fig.add_annotation(
            text="Quantity", showarrow=False,
            xref="paper", x=0, xanchor="right", xshift=-12,
            yref="paper", y=0, yanchor="top", yshift=-4,
            font=dict(size=12),
        )
        fig.update_layout(
            margin=dict(l=0, r=0, t=8, b=60),
            legend=dict(orientation="h", y=-0.2, yanchor="top",
                        font=dict(size=10), title_text=""),
        )
        st.plotly_chart(fig)

# =====================================================================
# BARIS 5: export (paling bawah, rata kanan)
# =====================================================================
def build_excel(year):
    """laporan Excel untuk tahun terpilih"""
    klas = classify(year).merge(produk_df, on="Produk_Key")
    klas["G_rata"] = klas["G_rata"].replace([np.inf, -np.inf], np.nan)
    klas = klas[["Nama_Produk", "Kategori", "Tahap", "Alasan", "G_rata"]]
    klas.columns = ["Nama Produk", "Kategori", "Tahap", "Alasan", "Rata-rata Pertumbuhan 3 Bulan (%)"]
    klas = klas.sort_values("Nama Produk").reset_index(drop=True) # sort sesuai nama produk alphabetical

    s = kpi_tahap(year)
    sr = success_rate(year)
    ringkasan = pd.DataFrame(
        {
            "Indikator": [
                "Total Revenue (Rp)", "Jumlah Introduction", "Jumlah Growth", "Jumlah Maturity",
                "Jumlah Decline", "  - berhenti terjual", "  - penjualan menurun",
                "Persentase Growth (%)", "Persentase Decline (%)", "Success Rate (%)",
            ],
            "Nilai": [
                total_revenue, s["Introduction"], s["Growth"], s["Maturity"], s["Decline"],
                s["berhenti"], s["menurun"], round(s["pct_growth"], 1), round(s["pct_decline"], 1),
                "tahun dasar" if sr is None else (round(sr[0] / sr[1] * 100, 1) if sr[1] else "-"),
            ],
        }
    )

    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        klas.to_excel(w, sheet_name="Klasifikasi Produk", index=False)
        ringkasan.to_excel(w, sheet_name="Ringkasan", index=False)
    return buf.getvalue()


st.write("")
_, export_col = st.columns([6.5, 1.5])

with export_col:
    st.download_button(
        "Export to Excel",
        data=build_excel(year),
        file_name=f"livinaFashionReport_{year}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )