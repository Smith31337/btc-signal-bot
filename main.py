from flask import Flask, request, jsonify
import requests
import logging
from datetime import datetime
import os

app = Flask(__name__)

# === НАСТРОЙКИ ===
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN')
CHAT_ID = int(os.environ.get('CHAT_ID', '172606168'))
WEBHOOK_SECRET = os.environ.get('WEBHOOK_SECRET', 'QQQwww111!!!')

SUPPORT_LEVEL = 80113
RESISTANCE_LEVEL = 86620

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger(__name__)


# === РАСЧЁТ RSI (Алгоритм Уайлдера, как на TradingView) ===
def calculate_rsi(klines, period=14):
    try:
        closes = [float(k[4]) for k in klines]
        if len(closes) < period + 1:
            return 50.0
        
        deltas = [closes[i] - closes[i-1] for i in range(1, len(closes))]
        gains = [d if d > 0 else 0.0 for d in deltas]
        losses = [-d if d < 0 else 0.0 for d in deltas]
        
        avg_gain = sum(gains[:period]) / period
        avg_loss = sum(losses[:period]) / period
        
        for i in range(period, len(gains)):
            avg_gain = (avg_gain * (period - 1) + gains[i]) / period
            avg_loss = (avg_loss * (period - 1) + losses[i]) / period
            
        if avg_loss == 0:
            return 100.0
            
        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))
    except Exception as e:
        logger.error(f'Ошибка расчёта RSI: {e}')
        return 50.0


# === ПОЛУЧЕНИЕ ДАННЫХ С BINANCE ===
def get_btc_data():
    """Получает текущую цену и RSI(14) на 4H с Binance"""
    try:
        url = "https://api.binance.com/api/v3/klines?symbol=BTCUSDT&interval=4h&limit=100"
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        klines = response.json()
        
        current_price = float(klines[-1][4])
        current_rsi = calculate_rsi(klines, period=14)
        
        return current_price, current_rsi
    except Exception as e:
        logger.error(f'Ошибка получения данных Binance: {e}')
        return None, None


# === ОТПРАВКА В TELEGRAM ===
def send_telegram_message(message):
    url = f'https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage'
    payload = {
        'chat_id': CHAT_ID,
        'text': message
    }
    try:
        response = requests.post(url, json=payload, timeout=10)
        logger.info(f'Telegram response: {response.status_code}')
        response.raise_for_status()
        return True
    except Exception as e:
        logger.error(f'Ошибка отправки: {e}')
        return False


# === АНАЛИЗ СИГНАЛА ===
def analyze_signal(rsi, price, signal_type, volume_ratio=1.0):
    try:
        signals = []
        score = 0

        if rsi < 25:
            signals.append("RSI в глубокой перепроданности (< 25)")
            score += 1
        elif rsi < 30:
            signals.append("RSI в зоне перепроданности (< 30)")
            score += 1
        elif rsi < 40:
            signals.append("RSI приближается к перепроданности")
            score += 0.5
        else:
            signals.append("RSI не в зоне перепроданности")

        distance = ((price - SUPPORT_LEVEL) / SUPPORT_LEVEL) * 100
        if distance < 1:
            signals.append(f"Цена на поддержке ({distance:.2f}%)")
            score += 1
        elif distance < 3:
            signals.append(f"Цена близко к поддержке ({distance:.2f}%)")
            score += 1
        elif distance < 5:
            signals.append(f"Цена приближается к поддержке ({distance:.2f}%)")
            score += 0.5
        else:
            signals.append(f"Цена далеко от поддержки ({distance:.2f}%)")

        if volume_ratio > 1.5:
            signals.append(f"Объем выше среднего в {volume_ratio:.1f}x")
            score += 1
        elif volume_ratio > 1.2:
            signals.append(f"Объем выше среднего ({volume_ratio:.1f}x)")
            score += 0.5
        else:
            signals.append(f"Объем средний ({volume_ratio:.1f}x)")

        confidence = (score / 3) * 100
        if score >= 2.5:
            rec = "СИЛЬНЫЙ СИГНАЛ К ПОКУПКЕ!"
            action = "Вход 70-80% капитала"
        elif score >= 1.5:
            rec = "УМЕРЕННЫЙ СИГНАЛ"
            action = "Вход 30-50% капитала"
        else:
            rec = "СЛАБЫЙ СИГНАЛ"
            action = "Ждать"

        stop_loss = price * 0.96
        risk_reward = (RESISTANCE_LEVEL - price) / (price - stop_loss) if price > stop_loss else 0

        message = f"""
BTC SIGNAL: {signal_type}

Анализ:
{chr(10).join(signals)}

Цена: ${price:,.0f}
RSI (4H): {rsi:.2f}
Объем: {volume_ratio:.1f}x

Уровни:
- Поддержка: ${SUPPORT_LEVEL:,}
- Сопротивление: ${RESISTANCE_LEVEL:,}

Рекомендация: {rec}
{action}

Параметры:
- Стоп-лосс: ${stop_loss:,.0f} (-4%)
- Тейк-профит: ${RESISTANCE_LEVEL:,}
- Риск/Прибыль: 1:{risk_reward:.2f}
- Уверенность: {confidence:.0f}%

Время: {datetime.now().strftime('%d.%m.%Y %H:%M')}
"""
        return message, score
    except Exception as e:
        return f"Ошибка: {e}", 0


# === LIVE CHECK: Ручная проверка с реальными данными ===
@app.route('/live-check', methods=['GET'])
def live_check():
    try:
        price, rsi = get_btc_data()
        
        if price is None or rsi is None:
            return jsonify({'status': 'error', 'message': 'Не удалось получить данные с Binance'}), 500
        
        message, score = analyze_signal(rsi, price, "Ручная проверка (Live)")
        success = send_telegram_message(message)
        
        return jsonify({
            'status': 'success' if success else 'failed',
            'rsi': round(rsi, 2),
            'price': price,
            'score': score
        })
    except Exception as e:
        logger.error(f'Ошибка live-check: {e}')
        return jsonify({'status': 'error', 'message': str(e)}), 500


# === WEBHOOK (на будущее) ===
@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        data = request.json
        if data.get('secret') != WEBHOOK_SECRET:
            return jsonify({'status': 'error'}), 401

        message, score = analyze_signal(
            rsi=float(data.get('rsi', 100)),
            price=float(data.get('price', 0)),
            signal_type=data.get('signal_type', 'Webhook'),
            volume_ratio=float(data.get('volume_ratio', 1.0))
        )
        success = send_telegram_message(message)
        return jsonify({'status': 'success' if success else 'failed', 'score': score})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


# === ТЕСТ ===
@app.route('/test', methods=['GET'])
def test():
    message, score = analyze_signal(rsi=28.5, price=81500, signal_type='Тест', volume_ratio=1.8)
    success = send_telegram_message(message)
    return jsonify({'status': 'success' if success else 'failed', 'score': score})


# === СТАТУС ===
@app.route('/status', methods=['GET'])
def status():
    return jsonify({
        'status': 'online',
        'time': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    })


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
