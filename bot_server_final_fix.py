import gspread
from oauth2client.service_account import ServiceAccountCredentials
import requests
import datetime
from flask import Flask, request, Response
import os
import json
import pandas as pd
import matplotlib
matplotlib.use('Agg') # Mengatur backend matplotlib agar non-interaktif
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter
import traceback
import numpy as np
import time

# ==============================================================================
# BAGIAN 1: PENGATURAN & KREDENSIAL
# ==============================================================================

# --- GANTI DENGAN INFORMASI ANDA ---
NAMA_SPREADSHEET = os.environ.get("NAMA_SPREADSHEET")
AUTHORIZED_USER_ID = int(os.environ.get("AUTHORIZED_USER_ID"))
TELEGRAM_TOKEN = os.environ.get ("TELEGRAM_TOKEN")
TELEGRAM_API_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"
# ------------------------------------

# Inisialisasi Flask App
app = Flask(__name__)

# ==============================================================================
# BAGIAN 2: FUNGSI-FUNGSI LOGIKA
# ==============================================================================

def setup_google_sheets():
    scope = ["https://spreadsheets.google.com/feeds", 'https://www.googleapis.com/auth/spreadsheets',
             "https://www.googleapis.com/auth/drive.file", "https://www.googleapis.com/auth/drive"]
    google_creds_json_str = os.environ.get('GOOGLE_CREDENTIALS_JSON')
    creds_dict = json.loads(google_creds_json_str)
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    client = gspread.authorize(creds)
    sheet = client.open(NAMA_SPREADSHEET).sheet1
    return sheet

def get_btc_price_from_binance():
    """Mengambil harga BTC/USDT terkini dari Binance dengan penanganan error lebih baik."""
    url = "https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT"
    try:
        response = requests.get(url, timeout=10)

        # Periksa apakah permintaan berhasil (kode status 2xx)
        response.raise_for_status()

        # Memeriksa apakah kunci 'price' ada sebelum mengaksesnya
        if 'price' in response.json():
            return float(response.json()['price'])
        else:
            print("Eror: Kunci 'price' tidak ditemukan dalam respons Binance.")
            return None

    except requests.exceptions.RequestException as e:
        if e.response and e.response.status_code == 418:
            print("Error 418: Permintaan terlalu banyak, coba lagi setelah beberapa detik.")
            time.sleep(5)  # Menunggu 5 detik sebelum mencoba lagi
            return get_btc_price_from_binance()  # Coba lagi
        print(f"Gagal mengambil harga dari Binance. Error: {e}")
        return None

def get_usd_to_idr_rate():
    """Mengambil kurs USD ke IDR."""
    url = "https://open.er-api.com/v6/latest/USD"
    try:
        response = requests.get(url)
        response.raise_for_status()  # Memeriksa jika ada masalah dengan API
        return float(response.json()['rates']['IDR'])
    except requests.exceptions.RequestException as e:
        print(f"Gagal mengambil kurs USD ke IDR. Error: {e}")
        return None

def get_portfolio_status():
    try:
        sheet = setup_google_sheets()
        values = sheet.get_all_values()
        header = values[0]
        data = values[1:]

        btc_price = get_btc_price_from_binance()
        idr_rate = get_usd_to_idr_rate()
        if btc_price is None or idr_rate is None:
            return "Gagal mengambil harga BTC atau kurs IDR. Silakan coba lagi."
        
        harga_btc_idr_saat_ini = btc_price * idr_rate
        
        portfolio_status = []  # Tambah inisialisasi list
        
        for row in data:
            tanggal = row[0]
            modal_deposit = float(row[1])
            
            try:
                jumlah_btc_didapat = row[3].replace(',', '.')
                jumlah_btc_didapat = float(jumlah_btc_didapat)
            except ValueError:
                print(f"Error konversi nilai BTC: {row[3]}")
                jumlah_btc_didapat = 0.0

            nilai_kini = jumlah_btc_didapat * harga_btc_idr_saat_ini
            keuntungan = nilai_kini - modal_deposit
            keuntungan_persen = (keuntungan / modal_deposit) * 100 if modal_deposit > 0 else 0

            status = "📈" if keuntungan >= 0 else "📉"
            keuntungan_str = f"Untung Rp {keuntungan:,.0f} ({keuntungan_persen:.2f}%)" if keuntungan >= 0 else f"Kerugian Rp {abs(keuntungan):,.0f} ({keuntungan_persen:.2f}%)"

            portfolio_status.append(f"*Tanggal: {tanggal}*\n"
                                    f"Deposit: `Rp {modal_deposit:,.0f}`\n"
                                    f"BTC Dibeli: `{jumlah_btc_didapat:.8f}`\n"
                                    f"Nilai Kini: `Rp {nilai_kini:,.0f}`\n"
                                    f"Status: {status} {keuntungan_str}\n")

        return "\n--------------------\n".join(portfolio_status)
    
    except Exception as e:
        print(f"Gagal mengambil status portofolio: {e}")
        return "Gagal mengambil data status portofolio."
        
def create_and_save_chart():
    """Membaca data, menghitung statistik, dan membuat dasbor grafik canggih."""
    try:
        print("Membuat grafik...")
        sheet = setup_google_sheets()
        values = sheet.get_all_values()
        header = values[0]
        data = values[1:]
        
        harga_btc_idr_saat_ini = get_btc_price_from_binance() * get_usd_to_idr_rate()

        if len(data) < 2:
            print("Tidak ada data yang cukup untuk dibuat grafik.")
            return None

        df = pd.DataFrame(data, columns=header)
        df['Tanggal'] = pd.to_datetime(df['Tanggal'], format="%Y-%m-%d %H:%M:%S")
        df['Modal Deposit (IDR)'] = pd.to_numeric(df['Modal Deposit (IDR)'])
        df['Jumlah BTC Didapat'] = pd.to_numeric(df['Jumlah BTC Didapat'].astype(str).str.replace(',', '.', regex=False))
        df = df.sort_values(by='Tanggal').reset_index(drop=True)

        df['Total Modal (IDR)'] = df['Modal Deposit (IDR)'].cumsum()
        df['Total BTC'] = df['Jumlah BTC Didapat'].cumsum()
        df['Nilai Aset (IDR)'] = df['Total BTC'] * harga_btc_idr_saat_ini
        df['Keuntungan (IDR)'] = df['Nilai Aset (IDR)'] - df['Total Modal (IDR)']
        df['Keuntungan (%)'] = (df['Keuntungan (IDR)'] / df['Total Modal (IDR)']).replace([np.inf, -np.inf], 0).fillna(0) * 100

        final_modal = df['Total Modal (IDR)'].iloc[-1]
        final_nilai_aset = df['Nilai Aset (IDR)'].iloc[-1]
        final_total_btc = df['Total BTC'].iloc[-1]
        keuntungan_rp = final_nilai_aset - final_modal
        keuntungan_persen = (keuntungan_rp / final_modal) * 100 if final_modal > 0 else 0

        plt.style.use('dark_background')
        fig, (ax_text, ax_chart) = plt.subplots(
            nrows=2, ncols=1, figsize=(9, 16), facecolor='#121212', 
            gridspec_kw={'height_ratios': [1, 4]}
        )
        fig.patch.set_edgecolor('white')
        fig.patch.set_linewidth(4)
        
        ax_text.set_facecolor('#121212')
        for spine in ['top', 'right', 'left', 'bottom']: ax_text.spines[spine].set_visible(False)
        ax_text.tick_params(axis='both', which='both', length=0)
        ax_text.set_xticklabels([])
        ax_text.set_yticklabels([])
        ax_text.set_ylim(0, 1)
        
        ax_text.text(0.5, 1, 'Riwayat Investasi', fontsize=22, fontweight='bold', color='white', ha='center')
        
        warna_nilai_investasi = '#3776c8'
        warna_modal_investasi = 'white'
        profit_color = 'lime' if keuntungan_persen >= 0 else 'red'

        ax_text.text(0.05, 0.6, 'Modal Investasi', color='grey', fontsize=15, ha='left')
        ax_text.text(0.05, 0.45, f'Rp {final_modal:,.0f}', color=warna_modal_investasi, fontsize=18, fontweight='bold', ha='left') 
        ax_text.text(0.05, 0.25, 'Total Aset Dibeli', color='grey', fontsize=12, ha='left')
        ax_text.text(0.05, 0.1, f'{final_total_btc:.8f} BTC', color='white', fontsize=14, ha='left')

        ax_text.text(0.95, 0.6, 'Nilai Investasi', color='white', fontsize=15, ha='right')
        ax_text.text(0.95, 0.45, f'Rp {final_nilai_aset:,.0f}', color=warna_nilai_investasi, fontsize=18, fontweight='bold', ha='right') 
        ax_text.text(0.95, 0.35, f'(Harga BTC: Rp {harga_btc_idr_saat_ini:,.0f})', color='yellow', fontsize=9, ha='right', fontweight='bold')
        
        profit_arrow = '▲' if keuntungan_persen >= 0 else '▼'
        profit_text_label = "Keuntungan" if keuntungan_persen >= 0 else "Kerugian"
        ax_text.text(0.95, 0.15, profit_text_label, color=profit_color, fontsize=12, ha='right')
        ax_text.text(0.95, 0.0, f'{profit_arrow} {keuntungan_persen:.1f}%', color=profit_color, fontsize=16, ha='right')

        ax_chart.set_facecolor('#121212')
        
        data_min = min(df['Total Modal (IDR)'].min(), df['Nilai Aset (IDR)'].min())
        data_max = max(df['Total Modal (IDR)'].max(), df['Nilai Aset (IDR)'].max())
        data_range = data_max - data_min
        if data_range == 0: data_range = data_max
        df['Nilai_Aset_Plot'] = (df['Nilai Aset (IDR)'] - data_min) / data_range
        start_modal_norm = (df['Total Modal (IDR)'].iloc[0] - data_min) / data_range
        end_modal_norm = (df['Total Modal (IDR)'].iloc[-1] - data_min) / data_range

        ax_chart.plot(df['Tanggal'], df['Nilai_Aset_Plot'], color=warna_nilai_investasi, linewidth=2.5, marker='o', markersize=5, zorder=10)
        ax_chart.plot([df['Tanggal'].iloc[0], df['Tanggal'].iloc[-1]], [start_modal_norm, end_modal_norm], color=warna_modal_investasi, linewidth=1.5, marker='o', markersize=5, alpha=0.4)

        profit_chart_base = 1.05
        profit_chart_height = 0.25
        profit_min, profit_max = df['Keuntungan (%)'].min(), df['Keuntungan (%)'].max()
        profit_range = profit_max - profit_min
        if profit_range == 0: profit_range = 1
        df['Profit_Plot_Y'] = (((df['Keuntungan (%)'] - profit_min) / profit_range) * profit_chart_height) + profit_chart_base
        ax_chart.plot(df['Tanggal'], df['Profit_Plot_Y'], color=profit_color, linewidth=2, marker='o', markersize=4)
        zero_pct_pos = (((0 - profit_min) / profit_range) * profit_chart_height) + profit_chart_base
        ax_chart.axhline(y=zero_pct_pos, color='white', linestyle='--', linewidth=1, alpha=0.3)

        last_label_date = None
        for index, row in df.iterrows():
            current_date_str = row['Tanggal'].strftime('%d/%m')
            if index == 0 or index == len(df) - 1 or current_date_str != last_label_date:
                ax_chart.text(row['Tanggal'], row['Nilai_Aset_Plot'], f" {current_date_str}", fontsize=8, fontweight='bold', color=warna_nilai_investasi, ha='left', va='bottom')
                ax_chart.text(row['Tanggal'], row['Profit_Plot_Y'], f" {current_date_str}", fontsize=7, color=profit_color, ha='left', va='bottom', fontweight='bold')
                last_label_date = current_date_str
        
        for spine in ['top', 'right', 'left', 'bottom']: ax_chart.spines[spine].set_visible(False)
        ax_chart.tick_params(axis='both', which='both', length=0)
        ax_chart.set_xticklabels([])
        ax_chart.set_yticklabels([])
        ax_chart.set_xlabel('')
        ax_chart.set_ylabel('')

        chart_filename = "grafik_investasi.png"
        plt.savefig(chart_filename, dpi=150, bbox_inches='tight', pad_inches=0.1, facecolor=fig.get_facecolor())
        plt.close()
        
        print(f"Grafik berhasil disimpan sebagai {chart_filename}")
        
        # --- PERUBAHAN DI SINI: Mengembalikan data statistik ---
        stats = {
            "filename": chart_filename,  # Pastikan path file yang benar
            "keuntungan_rp": keuntungan_rp,
            "keuntungan_persen": keuntungan_persen
        }
        return stats
        # ----------------------------------------------------
    except Exception as e:
        print(f"Gagal membuat grafik. Laporan Eror Lengkap:")
        traceback.print_exc()
        return None
def get_btc_volatility(days=30):
    try:
        url = f"https://api.binance.com/api/v3/klines?symbol=BTCUSDT&interval=1d&limit={days}"
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()
        closes = [float(candle[4]) for candle in data]
        if len(closes) < 2:
            return None
        returns = np.log(np.array(closes[1:]) / np.array(closes[:-1]))
        vol = np.std(returns) * np.sqrt(365) * 100
        return vol
    except Exception as e:
        print(f"Error getting volatility: {e}")
        traceback.print_exc()
        return None
# ==============================================================================
# BAGIAN 3: FUNGSI KOMUNIKASI TELEGRAM
# ==============================================================================

def send_telegram_message(chat_id, message_text):
    """Mengirim pesan teks ke pengguna melalui Telegram Bot API."""
    url = f"{TELEGRAM_API_URL}/sendMessage"
    # Menggunakan parse_mode='Markdown' agar format tebal (*...*) bisa berfungsi
    data = {"chat_id": chat_id, "text": message_text, "parse_mode": "Markdown"}
    try:
        response = requests.post(url, json=data)
        response.raise_for_status()
        print(f"Berhasil mengirim balasan teks ke chat_id: {chat_id}")
    except requests.exceptions.RequestException as e:
        print(f"Gagal mengirim balasan teks: {e}")

def send_telegram_photo(chat_id, photo_path, caption=""):
    """Mengirim gambar ke pengguna melalui Telegram Bot API."""
    url = f"{TELEGRAM_API_URL}/sendPhoto"
    with open(photo_path, 'rb') as photo_file:
        files = {'photo': photo_file}
        data = {'chat_id': chat_id, 'caption': caption}
        try:
            response = requests.post(url, files=files, data=data)
            response.raise_for_status()
            print(f"Pesan gambar berhasil dikirim ke chat_id: {chat_id}")
        except requests.exceptions.RequestException as e:
            print(f"Gagal mengirim pesan gambar: {e}")

# ==============================================================================
# BAGIAN 4: SERVER WEBHOOK FLASK (UNTUK TELEGRAM)
# ==============================================================================

@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.get_json()
    try:
        # 1. Ekstrak informasi penting dari data Telegram
        if 'message' in data and 'text' in data['message']:
            chat_id = data['message']['chat']['id']
            message_body = data['message']['text'].lower()

            print(f"Pesan dari: {chat_id} | Isi: {message_body}")

            # 2. Logika Perintah (SAMA SEPERTI SEBELUMNYA, HANYA BEDA FUNGSI PENGIRIMAN)
            if message_body.startswith('dca'):
                parts = message_body.split()
                if len(parts) == 2 and parts[1].isdigit():
                    jumlah_dca = int(parts[1])
                    send_telegram_message(chat_id, f"Memproses permintaan DCA sebesar Rp {jumlah_dca:,.0f}...")

                    # --- Proses dan catat DCA (logika ini tidak berubah) ---
                    harga_btc_usd = get_btc_price_from_binance()
                    kurs_usd_idr = get_usd_to_idr_rate()
                    harga_final_btc_idr = harga_btc_usd * kurs_usd_idr
                    jumlah_btc_didapat = jumlah_dca / harga_final_btc_idr
                    
                    sheet = setup_google_sheets()
                    tanggal_hari_ini = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    sheet.append_row([tanggal_hari_ini, jumlah_dca, harga_final_btc_idr, jumlah_btc_didapat])
                    
                    # ... (logika perhitungan keuntungan tetap sama) ...
                    all_btc_values = sheet.col_values(4) 
                    total_btc_owned = sum([float(str(i).replace(',', '.')) for i in all_btc_values[1:]])
                    all_modal_values = sheet.col_values(2)
                    total_modal = sum([float(str(i).replace(',', '.')) for i in all_modal_values[1:]])
                    nilai_aset = total_btc_owned * harga_final_btc_idr
                    keuntungan_rp = nilai_aset - total_modal
                    keuntungan_persen = (keuntungan_rp / total_modal) * 100 if total_modal > 0 else 0
                    
                    # --- Kirim Jawaban Teks (menggunakan fungsi Telegram) ---
                    balasan_sukses = (
                        f"✅ *Sukses!* Deposit DCA telah dicatat.\n\n"
                        f"Jumlah: Rp {jumlah_dca:,.2f}\n"
                        f"Harga BTC: Rp {harga_final_btc_idr:,.2f}\n"
                        f"BTC Didapat: `{jumlah_btc_didapat:.8f}` BTC\n\n" # Gunakan `...` untuk format monospaced di Telegram
                        f"Total Aset Anda: *{total_btc_owned:.8f} BTC*\n"
                        f"*Akumulasi Riwayat Keuntungan Anda: Rp {keuntungan_rp:,.2f} ({keuntungan_persen:.1f}%)*"
                    )
                    send_telegram_message(chat_id, balasan_sukses)

                    # --- Kirim Jawaban Grafik (menggunakan fungsi Telegram) ---
                    send_telegram_message(chat_id, "Membuat dasbor grafik terbaru...")
                    chart_data = create_and_save_chart()  # Pastikan menerima stats yang benar
                    if chart_data:
                        send_telegram_photo(chat_id, chart_data['filename'], caption="Berikut dasbor investasi Anda.")
                    else:
                        send_telegram_message(chat_id, "Maaf, data investasi belum cukup untuk membuat grafik.")
                else:
                    send_telegram_message(chat_id, "Format salah. Gunakan: dca [jumlah]\nContoh: dca 1000000")
            
            elif message_body == 'grafik':
                send_telegram_message(chat_id, "Sedang membuat dasbor grafik Anda, mohon tunggu sebentar...")

                # --- PERUBAHAN DI SINI: Menangkap data statistik ---
                chart_data = create_and_save_chart()
                if chart_data:
                    # Kirim foto terlebih dahulu, pastikan mengambil 'filename' dari chart_data
                    send_telegram_photo(chat_id, chart_data['filename'], caption="Berikut dasbor investasi Anda.")
                    
                    # Buat dan kirim pesan ringkasan
                    keuntungan_rp = chart_data['keuntungan_rp']
                    keuntungan_persen = chart_data['keuntungan_persen']
                    
                    if keuntungan_rp >= 0:
                        summary_text = f"📈 *Ringkasan Profit*\nSaat ini Anda mengalami keuntungan sebesar *Rp {keuntungan_rp:,.0f}* ({keuntungan_persen:.2f}%)."
                    else:
                        summary_text = f"📉 *Ringkasan Kerugian*\nSaat ini Anda mengalami kerugian sebesar *Rp {abs(keuntungan_rp):,.0f}* ({keuntungan_persen:.2f}%)."
                    
                    send_telegram_message(chat_id, summary_text)
                else:
                    send_telegram_message(chat_id, "Maaf, data investasi belum cukup untuk membuat grafik.")
            
            # Fitur tambahan untuk peringatan harga BTC
            elif message_body == 'cek harga':
                harga_btc_usd = get_btc_price_from_binance()  # Inisialisasi di luar blok if
                if harga_btc_usd is None:
                    send_telegram_message(chat_id, "Gagal mengambil harga BTC.")
                    return Response(status=200)
                kurs_usd_idr = get_usd_to_idr_rate()
                if kurs_usd_idr is None:
                    send_telegram_message(chat_id, "Gagal mengambil kurs IDR.")
                    return Response(status=200)
                harga_btc_idr = harga_btc_usd * kurs_usd_idr

                target_prices = [2000000000, 2500000000, 3000000000, 3500000000, 4000000000, 
                                 4500000000, 5000000000, 5500000000, 6000000000, 6500000000, 
                                 7000000000, 7500000000, 8000000000, 8500000000, 9000000000, 
                                 9500000000, 10000000000, 10500000000, 11000000000, 11500000000, 
                                 12000000000, 12500000000, 13000000000, 13500000000, 14000000000, 
                                 14500000000, 15000000000, 15500000000, 16000000000, 16500000000, 
                                 17000000000, 17500000000, 18000000000, 18500000000, 19000000000, 
                                 20000000000]
                
                targets_reached = [target for target in target_prices if harga_btc_idr >= target]
                
                if targets_reached:
                    for target in targets_reached:
                        send_telegram_message(chat_id, f"🚨 Peringatan! Harga BTC mencapai target Rp {target:,}.\nSaat ini harga BTC: Rp {harga_btc_idr:,.0f}")
                else:
                    send_telegram_message(chat_id, f"Harga BTC saat ini: Rp {harga_btc_idr:,.0f}\nBelum mencapai target apa pun.")
                    
            elif message_body == 'status':
                status_message = get_portfolio_status()
                send_telegram_message(chat_id, status_message)
            
            elif message_body == 'cek volatilitas':
                vol = get_btc_volatility()
                if vol is None:
                    send_telegram_message(chat_id, "Gagal menghitung volatilitas.")
                else:
                    threshold = 50  # Ubah sesuai kebutuhan
                    if vol > threshold:
                        msg = f"🚨 Alert! Volatilitas BTC tinggi: {vol:.2f}% (30 hari annualized)"
                    else:
                        msg = f"Volatilitas BTC: {vol:.2f}% (30 hari annualized)"
                    send_telegram_message(chat_id, msg)
            
            else:
                send_telegram_message(chat_id, "Perintah tidak dikenali. Gunakan 'dca [jumlah]', 'grafik', 'status', atau 'cek harga', 'cek volatilitas'.")

    except Exception as e:
        print(f"Error memproses pesan. Laporan Eror Lengkap:")
        traceback.print_exc()

    return Response(status=200)

# ==============================================================================
# BAGIAN 5: MENJALANKAN SERVER
# ==============================================================================
if __name__ == "__main__":
    app.run(port=5000)
