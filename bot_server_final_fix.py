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

# ==============================================================================
# BAGIAN 1: PENGATURAN & KREDENSIAL
# ==============================================================================

NAMA_SPREADSHEET = os.environ.get("NAMA_SPREADSHEET")
TELEGRAM_TOKEN = os.environ.get ("TELEGRAM_TOKEN")
TELEGRAM_API_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"
AUTHORIZED_USER_ID = int(os.environ.get("AUTHORIZED_USER_ID"))
# ------------------------------------

# Inisialisasi Flask App
app = Flask(__name__)

# ==============================================================================
# BAGIAN 2: FUNGSI-FUNGSI LOGIKA
# ==============================================================================

def setup_google_sheets(sheet_name):
    scope = ["https://spreadsheets.google.com/feeds", 'https://www.googleapis.com/auth/spreadsheets',
             "https://www.googleapis.com/auth/drive.file", "https://www.googleapis.com/auth/drive"]
    google_creds_json_str = os.environ.get('GOOGLE_CREDENTIALS_JSON')
    creds_dict = json.loads(google_creds_json_str)
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    client = gspread.authorize(creds)
    sheet = client.open(NAMA_SPREADSHEET).worksheet(sheet_name)
    return sheet

def get_btc_price_from_binance():
    """Mengambil harga BTC/USDT terkini dari Binance."""
    url = "https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT"
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()
        if 'price' in data:
            return float(data['price'])
        else:
            return None
    except (requests.exceptions.RequestException, ValueError) as e:
        print(f"Gagal mengambil atau memproses harga dari Binance. Eror: {e}")
        return None

def get_usd_to_idr_rate():
    """Mengambil kurs USD ke IDR."""
    url = "https://api.exchangerate-api.com/v4/latest/USD"
    response = requests.get(url, timeout=10)
    return float(response.json()['rates']['IDR'])
    
def get_detailed_history():
    """Membaca GSheet, mengambil harga terkini, dan menghitung statistik per baris."""
    try:
        sheet = setup_google_sheets("Tabel Master")
        
        # --- PERUBAHAN UTAMA: Membaca data berdasarkan posisi, bukan nama header ---
        values = sheet.get_all_values()
        data_rows = values[1:] # Lewati baris header
        
        harga_btc_usd = get_btc_price_from_binance()
        kurs_usd_idr = get_usd_to_idr_rate()
        
        if not data_rows or harga_btc_usd is None or kurs_usd_idr is None:
            return None

        harga_final_btc_idr = harga_btc_usd * kurs_usd_idr
        
        history_details = []
        for row in data_rows:
            # Mengakses data berdasarkan indeks kolom (A=0, B=1, C=2, D=3)
            tanggal_str = row[0]
            modal = float(row[1])
            btc_didapat = float(str(row[3]).replace(',', '.')) # Kolom D
            
            tanggal = datetime.datetime.strptime(tanggal_str, "%Y-%m-%d %H:%M:%S")
            
            nilai_kini = btc_didapat * harga_final_btc_idr
            keuntungan_rp = nilai_kini - modal
            keuntungan_persen = (keuntungan_rp / modal) * 100 if modal > 0 else 0
            
            history_details.append({
                "tanggal": tanggal.strftime("%d/%m/%Y"),
                "modal": modal,
                "btc_didapat": btc_didapat,
                "nilai_kini": nilai_kini,
                "keuntungan_rp": keuntungan_rp,
                "keuntungan_persen": keuntungan_persen
            })
        return history_details
    except Exception as e:
        print(f"Error di get_detailed_history: {e}")
        traceback.print_exc()
        return None

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
            "filename": chart_filename,
            "keuntungan_rp": keuntungan_rp,
            "keuntungan_persen": keuntungan_persen
        }
        return stats
        # ----------------------------------------------------
    except Exception as e:
        print(f"Gagal membuat grafik. Laporan Eror Lengkap:")
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
        if 'message' in data and 'text' in data['message']:
            incoming_chat_id = data['message']['chat']['id']
            message_body = data['message']['text'].lower()
            
            if incoming_chat_id != AUTHORIZED_USER_ID:
                print(f"Akses ditolak untuk user ID: {incoming_chat_id}")
                send_telegram_message(incoming_chat_id, "Maaf, Anda tidak diizinkan menggunakan bot ini.")
                return Response(status=200)

            print(f"Pesan dari: {incoming_chat_id} | Isi: {message_body}")

            if message_body.startswith('dca'):
                parts = message_body.split()
                if len(parts) == 2 and parts[1].isdigit():
                    jumlah_dca = int(parts[1])
                    send_telegram_message(incoming_chat_id, f"Memproses permintaan DCA sebesar Rp {jumlah_dca:,.0f}...")
                    
                    harga_btc_usd = get_btc_price_from_binance()
                    kurs_usd_idr = get_usd_to_idr_rate()
                    
                    if harga_btc_usd is None or kurs_usd_idr is None:
                        send_telegram_message(incoming_chat_id, "Maaf, gagal mengambil data harga saat ini. Coba lagi nanti.")
                        return Response(status=200)

                    harga_final_btc_idr = harga_btc_usd * kurs_usd_idr
                    jumlah_btc_didapat = jumlah_dca / harga_final_btc_idr
                    
                    sheet = setup_google_sheets("Tabel Master")
                    tanggal_hari_ini = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    sheet.append_row([tanggal_hari_ini, jumlah_dca, harga_final_btc_idr, jumlah_btc_didapat])
                    
                    all_btc_values = sheet.col_values(4) 
                    total_btc_owned = sum([float(str(i).replace(',', '.')) for i in all_btc_values[1:]])
                    
                    balasan_sukses = (
                        f"✅ *Sukses!* Deposit DCA telah dicatat.\n\n"
                        f"Jumlah: Rp {jumlah_dca:,.2f}\n"
                        f"Harga BTC: Rp {harga_final_btc_idr:,.2f}\n"
                        f"BTC Didapat: `{jumlah_btc_didapat:.8f}` BTC\n\n"
                        f"Total Aset Anda: *{total_btc_owned:.8f} BTC*"
                    )
                    send_telegram_message(incoming_chat_id, balasan_sukses)

                    send_telegram_message(incoming_chat_id, "Membuat dasbor grafik terbaru...")
                    chart_data = create_and_save_chart()
                    if chart_data:
                        send_telegram_photo(incoming_chat_id, chart_data['filename'], caption="Berikut dasbor investasi Anda.")
                else:
                    send_telegram_message(incoming_chat_id, "Format salah. Gunakan: dca [jumlah]\nContoh: dca 1000000")
            
            elif message_body == 'grafik':
                send_telegram_message(incoming_chat_id, "Sedang membuat dasbor grafik Anda, mohon tunggu sebentar...")
                
                chart_data = create_and_save_chart()
                if chart_data:
                    send_telegram_photo(incoming_chat_id, chart_data['filename'], caption="Berikut dasbor investasi Anda.")
                    
                    keuntungan_rp = chart_data['keuntungan_rp']
                    keuntungan_persen = chart_data['keuntungan_persen']
                    
                    if keuntungan_rp >= 0:
                        summary_text = f"📈 *Ringkasan Profit*\nSaat ini Anda mengalami keuntungan sebesar *Rp {keuntungan_rp:,.0f}* ({keuntungan_persen:.2f}%)."
                    else:
                        summary_text = f"📉 *Ringkasan Kerugian*\nSaat ini Anda mengalami kerugian sebesar *Rp {abs(keuntungan_rp):,.0f}* ({keuntungan_persen:.2f}%)."
                    
                    send_telegram_message(incoming_chat_id, summary_text)
                else:
                    send_telegram_message(incoming_chat_id, "Maaf, data investasi belum cukup untuk membuat grafik.")

            elif message_body == 'status':
                history = get_detailed_history()
                if history:
                    reply_message = "📊 *Riwayat Detil Portofolio Anda*\n\n"
                    
                    for trx in history:
                        status_emoji = "📈" if trx['keuntungan_rp'] >= 0 else "📉"
                        status_text = "Untung" if trx['keuntungan_rp'] >= 0 else "Rugi"
                        
                        trx_block = (
                            f"--------------------\n"
                            f"*{trx['tanggal']}*\n"
                            f"Deposit: `Rp {trx['modal']:,.0f}`\n"
                            f"BTC Dibeli: `{trx['btc_didapat']:.8f}`\n"
                            f"Nilai Kini: `Rp {trx['nilai_kini']:,.0f}`\n"
                            f"Status: {status_emoji} {status_text} Rp {abs(trx['keuntungan_rp']):,.0f} ({trx['keuntungan_persen']:.2f}%)"
                        )
                        reply_message += trx_block + "\n\n"
                    
                    send_telegram_message(incoming_chat_id, reply_message)
                else:
                    send_telegram_message(incoming_chat_id, "Gagal mengambil riwayat detil portofolio.")

            elif message_body.startswith('alert'):
                parts = message_body.split()
                if len(parts) == 4 and parts[1] == 'btc' and parts[2] in ['>', '<']:
                    try:
                        target_price = int(parts[3])
                        condition = parts[2]
                        
                        alert_sheet = setup_google_sheets("Alerts")
                        alert_sheet.append_row([incoming_chat_id, 'btc', condition, target_price])
                        
                        kondisi_teks = "di atas" if condition == '>' else "di bawah"
                        send_telegram_message(incoming_chat_id, f"🔔 *Alert Disimpan!* Saya akan memberitahu Anda jika harga BTC bergerak {kondisi_teks} Rp {target_price:,.0f}.")
                    except ValueError:
                        send_telegram_message(incoming_chat_id, "Format harga salah. Harap masukkan angka.")
                else:
                    send_telegram_message(incoming_chat_id, "Format perintah alert salah.\nGunakan: `alert btc [> atau <] [harga]`\nContoh: `alert btc > 2000000000`")

            else:
                send_telegram_message(incoming_chat_id, "Perintah tidak dikenali. Gunakan `dca [jumlah]`, `grafik`, `status`, atau `alert`.")

    except Exception as e:
        print(f"Error memproses pesan. Laporan Eror Lengkap:")
        traceback.print_exc()

    return Response(status=200)

# ==============================================================================
# BAGIAN 5: MENJALANKAN SERVER
# ==============================================================================
if __name__ == "__main__":
    app.run(port=5000)
